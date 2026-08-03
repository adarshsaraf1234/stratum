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
        6. Generate a plain-English summary string, e.g.:
           "3 high-severity events detected. CPU and latency degraded
            sharply starting at 03:15. No deployment events in the
            preceding window."
        7. Populate metadata: {"service": ..., "environment": ...}
           (extracted from signal tags)

        Returns:
            TemporalContext with domain="sre"
        """
        ...

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