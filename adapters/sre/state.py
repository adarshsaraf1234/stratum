"""
stratum/adapters/sre/state.py

SRE state builder — converts raw SRE signals into a TemporalContext using
deterministic rules and computations (no LLM involved).
"""

import logging
from datetime import datetime
from typing import Optional

import numpy as np

from stratum.core.schemas import Signal
from stratum.core.temporal_context import (
    TemporalContext,
    Event,
    Trend,
    Segment,
    Period,
)

logger = logging.getLogger(__name__)


class SREStateBuilder:
    """
    Builds a TemporalContext for the SRE domain.

    Deterministic logic only — this is the "brain" that turns raw
    metrics into structured, LLM-readable context.

    Usage:
        builder = SREStateBuilder()
        context = builder.build_state(signals)
    """

    # Threshold constants — match OTel signal units
    CPU_HIGH_THRESHOLD: float = 85.0            # percent
    LATENCY_SLA_SECONDS: float = 0.5           # seconds (500ms SLA)
    MEMORY_SPIKE_MULTIPLIER: float = 2.0       # >2x rolling mean = spike
    BREACH_DURATION_SECONDS: int = 180         # 3 consecutive minutes
    SPIKE_WINDOW: int = 5                      # samples for rolling baseline
    SPIKE_MULTIPLIER: float = 3.0              # >3x rolling mean = spike

    def __init__(self):
        pass

    def build_state(self, signals: list[Signal]) -> TemporalContext:
        """
        Convert a list of SRE Signals into a TemporalContext.

        Steps to implement:
        1. Separate signals by metric name (cpu_usage, memory_usage, latency_p99)
        2. Compute the window_start and window_end from the signal timestamps
        3. Compute a Trend for each metric using linear regression
           (numpy.polyfit on time-index vs value)
        4. Detect Events:
           - Threshold breach: value > threshold for N consecutive samples
             → Event(type="threshold_breach", severity="high"/"critical",
                     source=metric_name, raw_value=peak value)
           - Spikes: local peaks > 3x the rolling mean
             → Event(type="spike", severity="medium")
        5. Detect Segments via change-point detection:
           - Compute rolling mean/variance with a small window
           - Where variance jumps significantly, start a new segment
           - Label segments "stable" | "degrading" | "anomalous" | "recovering"
        6. Detect Periodicity via FFT on the metric with the widest range:
           - Use _detect_period() on the chosen metric
           - If a dominant cycle is found → Period object
           - Otherwise period remains None
        7. Generate a plain-English summary string, e.g.:
           "3 high-severity events detected. CPU and latency degraded
            sharply starting at 03:15. No deployment events in the
            preceding window."
        8. Populate metadata: {"service": ..., "environment": ...}
           (extracted from signal tags)

        Returns:
            TemporalContext with domain="sre"
        """
        # Edge case: no signals at all
        if not signals:
            return TemporalContext(
                domain="sre",
                window_start=datetime.utcnow(),
                window_end=datetime.utcnow(),
                summary="No signals received.",
            )

        # ── 1. Separate signals into per-metric point lists ───────────
        cpu_pts, mem_pts, lat_pts = [], [], []

        for signal in signals:
            if signal.name == "cpu_usage":
                cpu_pts.append((signal.timestamp, signal.value))
            elif signal.name == "memory_usage":
                mem_pts.append((signal.timestamp, signal.value))
            elif signal.name == "latency_p99":
                lat_pts.append((signal.timestamp, signal.value))

        # ── 2. Window bounds from the actual signal timestamps ─────────
        window_start = min(signals, key=lambda s: s.timestamp).timestamp
        window_end = max(signals, key=lambda s: s.timestamp).timestamp

        # ── 3. Trend per metric (linear regression) ──────────────────
        trends: dict[str, Trend] = {}
        trends["cpu"] = self._compute_trend(
            timestamps=[s[0] for s in cpu_pts],
            values=[s[1] for s in cpu_pts],
        )
        trends["memory"] = self._compute_trend(
            timestamps=[s[0] for s in mem_pts],
            values=[s[1] for s in mem_pts],
        )
        trends["latency"] = self._compute_trend(
            timestamps=[s[0] for s in lat_pts],
            values=[s[1] for s in lat_pts],
        )

        # ── 4. Events per metric ────────────────────────────────────
        events: list[Event] = []

        # Track which metrics already emitted events so trend detection
        # doesn't double-report a metric that already has a breach/spike.
        metric_seen_events: dict[str, bool] = {}
        metric_configs = [
            ("cpu_usage", [s[0] for s in cpu_pts], [s[1] for s in cpu_pts]),
            ("memory_usage", [s[0] for s in mem_pts], [s[1] for s in mem_pts]),
            ("latency_p99", [s[0] for s in lat_pts], [s[1] for s in lat_pts]),
        ]
        for metric_name, ts_list, val_list in metric_configs:
            metric_events = self._detect_events(
                timestamps=ts_list,
                values=val_list,
                metric_name=metric_name,
            )
            events += metric_events
            metric_seen_events[metric_name] = len(metric_events) > 0

        # Trend-based detection catches gradual degradations that no single
        # point-based spike/breach would flag (e.g. a slow memory leak).
        # Only add a trend event for a metric that has NO other events —
        # a breached/spiking metric is already represented.
        for metric_name, ts_list, val_list in metric_configs:
            if not metric_seen_events[metric_name]:
                events += self._detect_trend_events(
                    timestamps=ts_list,
                    values=val_list,
                    metric_name=metric_name,
                )

        events.sort(key=lambda e: e.timestamp)
        # ── 5. Pick the dominant metric (widest value range) ────────
        # Used for segments + period detection so we analyse the
        # signal with the most variation.
        def _metric_range(pts: list) -> float:
            vals = [v for _, v in pts]
            return max(vals) - min(vals) if vals else 0.0

        candidates = [
            ("cpu", cpu_pts),
            ("memory", mem_pts),
            ("latency", lat_pts),
        ]
        dominant_name, dominant_pts = max(
            candidates, key=lambda c: _metric_range(c[1])
        )

        # ── 6. Segments on the dominant metric ──────────────────────
        segments = self._detect_segments(
            timestamps=[s[0] for s in dominant_pts],
            values=[s[1] for s in dominant_pts],
        )

        # ── 7. Periodicity via FFT on the dominant metric ───────────
        period = self._detect_period(
            timestamps=[s[0] for s in dominant_pts],
            values=[s[1] for s in dominant_pts],
            signal_name=dominant_name,
        )

        # ── 8. Dominant trend — steepest |rate| of the three ────────
        # TemporalContext has ONE trend slot, so pick the most
        # extreme metric's trend to surface to the LLM.
        dominant_trend: Trend = max(
            trends.values(), key=lambda t: abs(t.rate), default=Trend()
        )

        # ── 9. Plain-English summary ────────────────────────────────
        summary = self._generate_summary(events, trends, segments)

        # ── 10. Metadata from signal tags ───────────────────────────
        metadata: dict = {}
        metadata["service"] = signals[0].tags.get("service", "unknown")
        metadata["environment"] = signals[0].tags.get("environment", "unknown")
        metadata["signal_count"] = len(signals)

        # ── 11. Construct and return the final TemporalContext ──────
        return TemporalContext(
            domain="sre",
            window_start=window_start,
            window_end=window_end,
            events=events,
            trend=dominant_trend,
            segments=segments,
            period=period,
            summary=summary,
            metadata=metadata,
        )

    def _compute_trend(self, timestamps: list[datetime], values: list[float]) -> Trend:
        """
        Compute a Trend from time-series data.

        Steps to implement:
        1. Convert datetimes to numeric time indices (seconds since first)
        2. Linear regression: slope, intercept = np.polyfit(time, values, 1)
        3. Normalize slope to "percent change per minute":
           rate = slope * 60 / mean(values) * 100
        4. Classify direction:
           > +0.5%  → "rising"
           < -0.5%  → "falling"
           |rate| < 0.5% → "flat"
           high stddev / mean > 0.3 → "volatile"
        4. Build description string, e.g.
           "CPU rising at +3.2% per minute over last 30 minutes"

        Returns:
            Trend
        """
        n = len(values)
        if n < 2:
            return Trend(direction="flat", rate=0.0, description="Insufficient data for trend.")

        # 1. Convert datetimes to seconds elapsed since the first sample
        t0 = timestamps[0]
        time_seconds = [(t - t0).total_seconds() for t in timestamps]

        # 2. Linear regression: fit y = slope * t + intercept
        slope, intercept = np.polyfit(time_seconds, values, 1)

        # 3. Normalise slope to "% change per minute" relative to the mean
        mean_val = float(np.mean(values))
        if mean_val == 0.0:
            rate_per_minute = 0.0
        else:
            rate_per_minute = (slope * 60.0) / mean_val * 100.0

        # 4. Classify direction
        stddev = float(np.std(values))
        cv = (stddev / mean_val) if mean_val > 0 else 0.0  # coefficient of variation

        if cv > 0.3:
            direction = "volatile"
        elif rate_per_minute > 0.5:
            direction = "rising"
        elif rate_per_minute < -0.5:
            direction = "falling"
        else:
            direction = "flat"

        # 5. Build human-readable description
        window_seconds = time_seconds[-1] if time_seconds else 0
        window_minutes = window_seconds / 60.0
        description = (
            f"Trend: {direction} | "
            f"Rate: {rate_per_minute:+.1f}% per minute | "
            f"Mean: {mean_val:.1f} | "
            f"Window: {window_minutes:.1f} min"
        )

        return Trend(direction=direction, rate=round(rate_per_minute, 2), description=description)

    def _detect_events(
        self,
        timestamps: list[datetime],
        values: list[float],
        metric_name: str,
    ) -> list[Event]:
        """
        Detect threshold breaches and spikes in a single metric stream.

        Steps to implement:
        1. For threshold breaches:
           - Use the static thresholds (CPU, MEMORY, LATENCY)
           - Find runs of consecutive samples above the threshold
           - If the run duration >= BREACH_DURATION_MINUTES:
             create Event(type="threshold_breach", severity=...)
             using the peak value in that run
        2. For spikes:
           - Compute rolling mean over ~5 samples
           - If value > 3x rolling mean → Event(type="spike", severity="medium")
        3. Deduplicate (don't emit both breach and spike for same point)
        4. Sort events by timestamp

        Returns:
            list[Event]
        """
        n = len(values)
        if n == 0:
            return []

        # ── Map metric → threshold value ──────────────────────────
        threshold_map = {
            "cpu_usage": self.CPU_HIGH_THRESHOLD,          # 85.0%
            "memory_usage": self.MEMORY_SPIKE_MULTIPLIER,   # 2x rolling mean
            "latency_p99": self.LATENCY_SLA_SECONDS,        # 0.5s
        }
        threshold = threshold_map.get(metric_name)
        if threshold is None:
            return []

        events: list[Event] = []

        # ═══════════════════════════════════════════════════════════
        # PASS 1: Threshold breach detection (consecutive-run scan)
        # ═══════════════════════════════════════════════════════════

        breached_indices: set[int] = set()

        # Memory has no fixed threshold — it uses a rolling-mean spike
        # approach instead, handled in Pass 2.
        if metric_name != "memory_usage":
            i = 0
            while i < n:
                if values[i] <= threshold:
                    i += 1
                    continue

                # Found the start of a breach run — scan until it ends
                run_start = i
                while i < n and values[i] > threshold:
                    i += 1
                run_end = i  # first index *after* the breach run

                run_duration = (
                    timestamps[run_end - 1] - timestamps[run_start]
                ).total_seconds()
                # Samples are spaced tick_interval apart, so a run of N
                # samples spans (N-1) * interval seconds. Add the interval
                # back so a 180-sample run (180 * 1s) counts as 180s and
                # satisfies the >= BREACH_DURATION_SECONDS check.
                if len(values[run_start:run_end]) >= 2:
                    sample_interval = (
                        (timestamps[run_start + 1] - timestamps[run_start]).total_seconds()
                        if run_start + 1 < run_end
                        else 0.0
                    )
                    run_duration += sample_interval

                if run_duration >= self.BREACH_DURATION_SECONDS:
                    peak_value = max(values[run_start:run_end])

                    # Severity by margin above threshold (cap-safe)
                    headroom = 100.0 - threshold if metric_name == "cpu_usage" else (
                        threshold * 5.0  # for latency: 0.5 × 5 = 2.5s ceiling
                    )
                    excess_ratio = (
                        (peak_value - threshold) / headroom
                    ) if headroom > 0 else 0.0

                    if excess_ratio > 0.5:
                        severity = "critical"
                    elif excess_ratio > 0.25:
                        severity = "high"
                    else:
                        severity = "medium"

                    events.append(Event(
                        timestamp=timestamps[run_start],
                        type="threshold_breach",
                        severity=severity,
                        source=metric_name,
                        description=(
                            f"{metric_name} breached {threshold} threshold "
                            f"for {run_duration:.0f}s (peak={peak_value:.1f})"
                        ),
                        raw_value=peak_value,
                    ))

                    # Mark these indices so spikes don't double-report
                    for idx in range(run_start, run_end):
                        breached_indices.add(idx)

        # ═══════════════════════════════════════════════════════════
        # PASS 2: Spike detection (rolling-baseline outliers)
        # ═══════════════════════════════════════════════════════════

        for i in range(self.SPIKE_WINDOW, n):
            if i in breached_indices:
                # Don't double-emit — Pass 1 already covered it
                continue

            rolling_baseline = np.mean(values[i - self.SPIKE_WINDOW : i])
            if rolling_baseline == 0.0:
                continue

            if values[i] > rolling_baseline * self.SPIKE_MULTIPLIER:
                events.append(Event(
                    timestamp=timestamps[i],
                    type="spike",
                    severity="low",
                    source=metric_name,
                    description=(
                        f"{metric_name} spiked to {values[i]:.1f} "
                        f"({values[i]/rolling_baseline:.1f}× rolling baseline {rolling_baseline:.1f})"
                    ),
                    raw_value=values[i],
                    expected_value=round(float(rolling_baseline), 2),
                ))

        # Sort by timestamp (guaranteed stable output order)
        events.sort(key=lambda e: e.timestamp)
        return events

    def _detect_trend_events(
        self,
        timestamps: list[datetime],
        values: list[float],
        metric_name: str,
    ) -> list[Event]:
        """
        Detect trend-based events (rising/falling) for a metric.

        Steps to implement:
        1. Compute the Trend using _compute_trend()
        2. If the trend is "rising" or "falling" and the rate exceeds
           a threshold (e.g., ±1% per minute), create an Event:
           - type="trend"
           - severity="medium" for moderate rates, "high" for extreme rates
           - source=metric_name
           - description=f"{metric_name} is {direction} at {rate:.1f}%/min"
        3. Return the list of detected trend events

        Returns:
            list[Event]
        """
        n = len(values)
        if n < 2:
            return []

        trend = self._compute_trend(timestamps, values)
        events: list[Event] = []

        # Net relative change over the window — guards against baseline
        # noise (sinusoid drift) being misinterpreted as a real trend.
        # The normalized %/min rate alone is too sensitive on short
        # windows (a ±8 point drift on a ~38 mean reads as +21%/min).
        net_change = (values[-1] - values[0]) / values[0] if values[0] != 0 else 0.0

        # Only rising trends are incidents — a falling metric is a
        # recovery, not a degradation.
        # 0.50 threshold: memory_leak rises 87-160% (fires); the normal
        # scenario's lognormal latency needs a first-to-last jump of >50%,
        # which is vanishingly rare across 100+ seeds.
        if trend.direction == "rising" and net_change >= 0.50:
            severity = "medium" if abs(trend.rate) < 3.0 else "high"
            events.append(Event(
                timestamp=timestamps[-1],
                type="trend",
                severity=severity,
                source=metric_name,
                description=f"{metric_name} is {trend.direction} at {trend.rate:+.1f}%/min",
                raw_value=round(float(values[-1]), 3),
            ))

        return events
    
    def _detect_segments(
        self,
        timestamps: list[datetime],
        values: list[float],
    ) -> list[Segment]:
        """
        Split the window into labeled segments using change-point detection.

        Steps to implement:
        1. Compute rolling variance with a small window (e.g. 5 samples)
        2. Where rolling variance changes by > 2x, mark a change point
        3. Build Segment objects between change points
        4. Label each segment based on its mean vs the overall window mean:
           - mean much higher → "degrading" or "anomalous"
           - mean much lower  → "recovering"
           - otherwise        → "stable"
        5. Assign dominant_signal = metric with highest variance in segment
           (for simplicity, use the provided values array's name)

        Returns:
            list[Segment]
        """
        n = len(values)
        window = 5
        if n < window + 1:
            return [
                Segment(
                    start=timestamps[0],
                    end=timestamps[-1],
                    label="stable",
                )
            ]

        # ── 1. Compute rolling variance ──────────────────────────────
        rolling_var = np.zeros(n)
        for i in range(window, n):
            rolling_var[i] = float(np.var(values[i - window : i]))

        # ── 2. Detect change points (variance jumps > 2×) ────────────
        # Skip the first window entries (still zero) to avoid false
        # positives from the transition out of the zero-padding.
        changes: list[int] = []
        for i in range(window + 1, n):
            if rolling_var[i - 1] > 0.0 and rolling_var[i] > rolling_var[i - 1] * 2.0:
                changes.append(i)

        # ── 3. Build segments between change points ──────────────────
        overall_mean = float(np.mean(values))
        overall_std = float(np.std(values))

        segments: list[Segment] = []
        start_idx = 0
        all_boundaries = changes + [n]

        for boundary in all_boundaries:
            end_idx = min(boundary, n)
            if end_idx <= start_idx:
                continue

            seg_vals = values[start_idx:end_idx]
            seg_mean = float(np.mean(seg_vals))
            seg_std = float(np.std(seg_vals))
            deviation = (
                (seg_mean - overall_mean) / overall_std if overall_std > 0 else 0.0
            )
            seg_cv = (seg_std / seg_mean) if seg_mean > 0 else 0.0

            # ── 4. Label the segment ─────────────────────────────
            if seg_cv > 0.4:
                label = "anomalous"
            elif deviation > 0.7:
                label = "degrading"
            elif deviation < -0.7:
                label = "recovering"
            else:
                label = "stable"

            segments.append(
                Segment(
                    start=timestamps[start_idx],
                    end=timestamps[end_idx - 1],
                    label=label,
                )
            )
            start_idx = end_idx

        # ── 5. Merge adjacent segments with the same label ──────────
        if len(segments) >= 2:
            merged: list[Segment] = [segments[0]]
            for seg in segments[1:]:
                prev = merged[-1]
                if seg.label == prev.label:
                    merged[-1] = Segment(
                        start=prev.start,
                        end=seg.end,
                        label=prev.label,
                    )
                else:
                    merged.append(seg)
            segments = merged

        return segments


    def _detect_period(
        self,
        timestamps: list[datetime],
        values: list[float],
        signal_name: str,
    ) -> Optional[Period]:
        """
        Detect cyclical patterns in a metric series via FFT.

        Steps to implement:
        1. Compute the time delta between consecutive samples
        2. Apply numpy FFT to the value series
        3. Find the dominant frequency (excluding DC / zero-frequency component)
        4. If the dominant component's magnitude exceeds ~30% of the total
           non-DC energy, treat it as a real cycle:
           - cycle_duration_seconds = 1 / dominant_freq
           - confidence = magnitude / total_non_dc_energy  (clamped 0–1)
           - description = f"Periodic with ~{cycle_duration_seconds:.0f}s cycle"
           - signal_source = signal_name
        5. Return Period(...) if confident, otherwise None

        For SRE specifically, periodicity is less common (most infrastructure
        metrics are aperiodic or driven by external load).  This method should
        return None in the vast majority of cases — a null Period is a valid
        signal that no regular cycle dominates the data.

        Returns:
            Period or None
        """
        n = len(values)
        if n < 4:
            return None

        # 1. Compute time delta (seconds) between samples
        deltas = np.diff([t.timestamp() for t in timestamps])
        if not np.all(deltas > 0):
            return None
        # 2. Apply FFT to the value series
        values = np.array(values)
        fft_vals = np.fft.fft(values)   
        fft_freqs = np.fft.fftfreq(n, d = np.mean(deltas))
        
        positive_mask = fft_freqs > 0
        pos_freqs = fft_freqs[positive_mask]
        pos_magnitudes = np.abs(fft_vals[positive_mask])

        # 4. Find the dominant frequency
        peak_index = int(np.argmax(pos_magnitudes))
        dominant_freq = float(pos_freqs[peak_index])
        peak_magnitude = float(pos_magnitudes[peak_index])

        # Guard: frequency must be a positive real cycle
        if dominant_freq <= 0.0:
            return None

        # 5. Confidence = share of the dominant component in total energy
        total_energy = float(np.sum(pos_magnitudes)) or 1.0
        confidence = min(peak_magnitude / total_energy, 1.0)

        # Need a clearly dominant cycle to report a period
        if confidence < 0.30:
            return None

        # Convert frequency → cycle duration
        cycle_seconds = 1.0 / dominant_freq

        # A cycle longer than the window itself is not a real cycle
        window_seconds = (timestamps[-1] - timestamps[0]).total_seconds()
        if cycle_seconds > window_seconds * 0.9:
            return None

        description = (
            f"Periodic with ~{cycle_seconds:.0f}s cycle "
            f"(dominant freq={dominant_freq:.4f} Hz)"
        )

        return Period(
            description=description,
            cycle_duration_seconds=round(cycle_seconds, 2),
            confidence=round(confidence, 3),
            signal_source=signal_name,
        )

    def _generate_summary(
        self,
        events: list[Event],
        trends: dict[str, Trend],
        segments: list[Segment],
    ) -> str:
        """
        Build a plain-English summary of the situation.

        Steps to implement:
        1. Count high/critical severity events
        2. Mention the top trend direction(s)
        3. Reference the most relevant segment label
        4. Keep it to 1-3 sentences — this goes into the LLM prompt

        Example:
            "2 high-severity events detected. CPU and latency degraded
             sharply starting at 03:15. Window is in a 'degrading' segment."

        Returns:
            str
        """
        sentences: list[str] = []

        # ── 1. Event summary sentence ──────────────────────────────
        high_severity = [
            e for e in events if e.severity in ("high", "critical")
        ]
        total_events = len(events)

        if total_events == 0:
            sentences.append("No anomalies detected.")
        else:
            if high_severity:
                sentences.append(
                    f"{len(high_severity)} high-severity event(s) detected "
                    f"out of {total_events} total."
                )
            else:
                sentences.append(
                    f"{total_events} event(s) detected, none reaching "
                    "high severity."
                )

        # ── 2. Trend sentence — the steepest |rate| trend ───────────
        if trends:
            metric_name, worst_trend = max(
                trends.items(), key=lambda kv: abs(kv[1].rate)
            )
            # Only mention the trend if it's meaningful
            if worst_trend.direction != "flat":
                sentences.append(
                    f"{metric_name} is {worst_trend.direction} "
                    f"at {worst_trend.rate:+.1f}%/min."
                )

        # ── 3. Segment sentence ────────────────────────────────────
        if segments:
            last_label = segments[-1].label
            sentences.append(f"Window is in a '{last_label}' segment.")

        # ── 4. Join into 1-3 sentences ─────────────────────────────
        return " ".join(sentences)
