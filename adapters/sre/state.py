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

    # Threshold constants (tune these)
    CPU_HIGH_THRESHOLD: float = 85.0        # percent
    MEMORY_HIGH_THRESHOLD: float = 90.0     # percent
    LATENCY_SLA_MS: float = 500.0           # milliseconds
    BREACH_DURATION_MINUTES: int = 3        # consecutive minutes required

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
        events += self._detect_events(
            timestamps=[s[0] for s in cpu_pts],
            values=[s[1] for s in cpu_pts],
            metric_name="cpu_usage",
        )
        events += self._detect_events(
            timestamps=[s[0] for s in mem_pts],
            values=[s[1] for s in mem_pts],
            metric_name="memory_usage",
        )
        events += self._detect_events(
            timestamps=[s[0] for s in lat_pts],
            values=[s[1] for s in lat_pts],
            metric_name="latency_p99",
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
        ...

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
        ...

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
        ...

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
        ...

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
        ...