"""
stratum/tests/test_state_builders.py

Integration tests for the SRE and Markets state builders.
These tests verify deterministic signal → TemporalContext logic.
"""

from datetime import datetime, timedelta

import pytest

from stratum.adapters.sre.signals import generate_incident_signals
from stratum.adapters.sre.state import SREStateBuilder
from stratum.adapters.markets.signals import generate_market_signals
from stratum.adapters.markets.state import MarketStateBuilder
from stratum.core.schemas import Signal


# ─── SRE State Builder Tests ───────────────────────────────────────────

def test_sre_cpu_spike_detects_threshold_breach():
    """
    generate_incident_signals("cpu_spike") → build_state()

    Assert:
    - context.domain == "sre"
    - At least one Event with type="threshold_breach"
      and source="cpu_usage"
    - The event's raw_value is > 85.0 (CPU_HIGH_THRESHOLD)
    """
    ...


def test_sre_memory_leak_trend_rising():
    """
    generate_incident_signals("memory_leak") → memory trend

    Assert:
    - The trend for memory_usage has direction == "rising"
    - The trend rate is positive
    """
    ...


def test_sre_latency_degradation_detects_breach():
    """
    generate_incident_signals("latency_degradation") → build_state()

    Assert:
    - At least one Event with type="threshold_breach"
      and source="latency_p99"
    """
    ...


def test_sre_normal_has_no_high_severity_events():
    """
    generate_incident_signals("normal") → build_state()

    Assert:
    - context.is_normal() is True
    - No events with severity in ("high", "critical")
    """
    ...


def test_sre_summary_non_empty():
    """
    Any incident scenario → summary string is non-empty and
    mentions the word "event" or "trend".
    """
    ...


def test_sre_segments_present_on_incident():
    """
    generate_incident_signals("cpu_spike") → build_state()

    Assert:
    - len(context.segments) >= 1
    - At least one segment has label != "stable"
    """
    ...


# ─── Markets State Builder Tests ──────────────────────────────────────

def test_markets_bull_run_state():
    """
    generate_market_signals("bull_run") → build_state()

    Assert:
    - context.domain == "markets"
    - The price trend direction is "rising"
    - At least one Event with type="volume_spike"
    - correct ticker from tags in metadata
    """
    ...


def test_markets_crash_state():
    """
    generate_market_signals("crash") → build_state()

    Assert:
    - The price trend direction is "falling"
    - At least one Event with type in ("breakdown", "volume_spike")
    """
    ...


def test_markets_consolidation_state():
    """
    generate_market_signals("consolidation") → build_state()

    Assert:
    - The price trend direction is "ranging"
    - No events with severity == "high"
    """
    ...


def test_markets_summary_contains_ticker():
    """
    generate_market_signals("bull_run", ticker="AAPL") → summary

    Assert:
    - "AAPL" appears in the summary string
    """
    ...


def test_markets_metadata_has_ticker():
    """
    build_state() → metadata["ticker"] == "AAPL"

    Also assert current_price is close to the last generated price
    (±1% tolerance).
    """
    ...


def test_markets_volume_spike_event_on_crash():
    """
    generate_market_signals("crash") → build_state()

    Assert:
    - At least one Event with type="volume_spike"
    - The event's raw_value is above the average volume
    """
    ...