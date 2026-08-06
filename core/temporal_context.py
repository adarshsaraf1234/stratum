"""
stratum/core/temporal_context.py

TemporalContext is the universal data structure that sits between raw signals
and LLM reasoning. It transforms noisy time-series data into structured,
deterministic context that an LLM can reason over reliably.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Event(BaseModel):
    """A salient event detected within a time window."""
    timestamp: datetime
    type: str
    severity: str = Field(default="medium")
    source: str
    description: str
    raw_value: float
    expected_value: Optional[float] = None


class Trend(BaseModel):
    """Deterministic trend information computed from the signal window."""
    direction: str = Field(default="flat")
    rate: float = Field(default=0.0)
    description: str = ""


class Segment(BaseModel):
    """A contiguous segment of the time window with a stable label."""
    start: datetime
    end: datetime
    label: str
    dominant_signal: str = ""


class Period(BaseModel):
    """Cyclical pattern detected in the signal window (T2SP periodicity extraction).

    Computed deterministically (typically via FFT on the signal series).
    None signals mean no strong cycle was detected.
    """
    description: str = ""
    cycle_duration_seconds: float = Field(default=0.0, ge=0.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    signal_source: str = ""  # which metric the cycle was detected on


class TemporalContext(BaseModel):
    """The universal structured context passed to the ReasoningAgent."""
    domain: str
    window_start: datetime
    window_end: datetime
    events: list[Event] = Field(default_factory=list)
    trend: Trend = Field(default_factory=Trend)
    segments: list[Segment] = Field(default_factory=list)
    period: Optional[Period] = None
    summary: str = ""
    metadata: dict = Field(default_factory=dict)

    @property
    def event_count(self) -> int:
        return len(self.events)

    @property
    def high_severity_events(self) -> list[Event]:
        return [e for e in self.events if e.severity in ("high", "critical")]

    @property
    def window_duration_seconds(self) -> float:
        return (self.window_end - self.window_start).total_seconds()

    def is_normal(self) -> bool:
        return len(self.high_severity_events) == 0 and self.trend.direction == "flat"