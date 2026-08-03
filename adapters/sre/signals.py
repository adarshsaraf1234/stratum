"""
stratum/adapters/sre/signals.py

SRE signal ingestion — generates mock infrastructure metrics and logs
that simulate real production incidents.
"""

import math
import random
from datetime import datetime, timedelta
from typing import Any, Optional

from stratum.core.schemas import Signal


def generate_incident_signals(
    incident_type: str = "cpu_spike",
    start_time: Optional[datetime] = None,
    duration_minutes: int = 30,
    interval_seconds: int = 30,
    seed: int = 42,
) -> list[Signal]:
    """
    Generate mock SRE signals for a given incident type.

    Supported incident_type values:
        - "cpu_spike"          : CPU usage spikes to 95%+ mid-window
        - "memory_leak"        : Memory usage grows linearly 50% → 95%
        - "latency_degradation": P99 latency climbs 100ms → 2000ms
        - "normal"             : Everything stays within healthy bounds

    Steps to implement:
    1. Seed the random module for deterministic output
    2. Compute number of data points from duration & interval
    3. For each timestamp in the window, compute metric values
       based on the incident type and progress through the window
    4. For each timestamp, append 3 Signal objects:
       - name="cpu_usage",    unit="%"
       - name="memory_usage", unit="%"
       - name="latency_p99",  unit="ms"
       Each with tags={"service": "payment-api", "environment": "production"}

    Pattern per incident type:
        cpu_spike:  cpu = 85-100% during middle 30% of window, else 30-50%
        memory_leak: cpu ~40%, mem = 50 + progress * 45, latency = 100 + mem * 3
        latency_degradation: cpu ~50%, mem ~65%, latency = 100 + progress * 1900
        normal:     cpu ~35%, mem ~55%, latency ~80-120ms

    Clamp all values to valid ranges (0-100 for %, >= 0 for ms).
    Round values to 1 decimal place.

    Returns:
        list[Signal] — chronologically ordered signal stream
    """
    ...


def parse_sre_signals(raw_data: Any) -> list[Signal]:
    """
    Convert raw SRE data (from API, JSON file, or CSV dump) into Signal objects.

    Expected raw_data formats:
        - list[dict] with keys: timestamp, metric, value, unit?, tags?
        - dict with a "signals" key containing the list above
        - JSON string that parses into one of the above

    Steps to implement:
    1. Normalize raw_data to a list of dicts (unwrap "signals" key if present)
    2. For each dict, validate required keys exist (timestamp, metric, value)
    3. Convert timestamp string → datetime (handle ISO 8601 and epoch)
    4. Name metrics consistently:
       - "cpu" | "cpu_usage" | "cpu-usage"  →  name="cpu_usage"
       - "mem" | "memory" | "memory_usage"  →  name="memory_usage"
       - "latency" | "p99" | "latency_p99"  →  name="latency_p99"
    5. Skip malformed entries with a warning log
    6. Sort final list by timestamp

    Returns:
        list[Signal]
    """
    ...