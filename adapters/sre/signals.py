"""
stratum/adapters/sre/signals.py

SRE signal ingestion using the official OpenTelemetry SDK.
Produces production-grade infrastructure metrics (CPU, memory, latency)
with configurable incident patterns, captured as Stratum Signal objects.

The OTel instruments are used for their standard metric names, units,
and attribute conventions — but values are also captured locally into
Signal objects so the rest of the Stratum pipeline (TemporalContext,
ReasoningAgent) can consume them without waiting for export cycles.
"""

import math
import random
import time
import logging
import json
import io
import pandas as pd
from datetime import datetime
from typing import Any, Optional

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider

from stratum.core.schemas import Signal

logger = logging.getLogger(__name__)

# ── Global MeterProvider — OTel allows exactly one per process ──────────
_METER: Optional[metrics.Meter] = None


def _get_meter() -> metrics.Meter:
    """Create (or return) the global OTel MeterProvider and Meter."""
    global _METER
    if _METER is None:
        provider = MeterProvider()
        metrics.set_meter_provider(provider)
        _METER = provider.get_meter("stratum.sre.simulation", "0.1.0")
    return _METER


# ── Signal capture — records every OTel reading as a Stratum Signal ──

class _SignalCapture:
    """Simple accumulator: stores Signal objects as the simulator ticks."""

    def __init__(self, service_name: str):
        self._signals: list[Signal] = []
        self._service_name = service_name

    def record(
        self,
        name: str,
        value: float,
        unit: str,
        extra_tags: Optional[dict[str, Any]] = None,
    ) -> None:
        self._signals.append(
            Signal(
                timestamp=datetime.now(),
                name=name,
                value=value,
                unit=unit,
                tags={
                    "service": self._service_name,
                    "environment": "production",
                    **(extra_tags or {}),
                },
            )
        )

    def signals(self) -> list[Signal]:
        return sorted(self._signals, key=lambda s: s.timestamp)


# ── Incident-type parameter presets ─────────────────────────────────────

INCIDENT_PRESETS: dict[str, dict[str, Any]] = {
    "cpu_spike": {
        "cpu_spike_probability": 0.30,
        "cpu_spike_min": 88.0,
        "cpu_spike_max": 99.1,
        "base_cpu_mean": 30.0,
        "memory_leak_enabled": False,
        "latency_spike_probability": 0.05,
    },
    "memory_leak": {
        "cpu_spike_probability": 0.03,
        "base_cpu_mean": 40.0,
        "memory_leak_enabled": True,
        "memory_leak_per_tick_bytes": (2_000_000, 4_000_000),
        "latency_spike_probability": 0.03,
    },
    "latency_degradation": {
        "cpu_spike_probability": 0.08,
        "base_cpu_mean": 50.0,
        "memory_leak_enabled": False,
        "latency_spike_probability": 0.30,
        "latency_degradation_range": (2.5, 6.2),
    },
    "normal": {
        "cpu_spike_probability": 0.01,
        "base_cpu_mean": 35.0,
        "memory_leak_enabled": False,
        "latency_spike_probability": 0.01,
    },
}


# ── Pipeline simulator ──────────────────────────────────────────────────

class OTelPipelineSimulator:
    """
    Simulates a production microservice pipeline using the official
    OpenTelemetry SDK, injecting configurable infrastructure anomalies.

    Every tick() writes live OTel gauge/histogram readings AND records
    a corresponding Stratum Signal through the capture accumulator.

    Usage:
        capture = _SignalCapture(service_name="checkout-service")
        sim = OTelPipelineSimulator(capture=capture, ...)
        for _ in range(60):
            sim.tick()
        signals = capture.signals()
    """

    def __init__(
        self,
        capture: _SignalCapture,
        service_name: str = "payment-api",
        incident_type: str = "normal",
        seed: int = 42,
    ):
        self.capture = capture
        self.service_name = service_name
        self.incident_type = incident_type
        self.preset = INCIDENT_PRESETS.get(incident_type, INCIDENT_PRESETS["normal"])

        # Deterministic seeded randomness
        random.seed(seed)
        self._rng = random.Random(seed)

        # ── Standard OTel instruments (industry metric names & units) ──
        meter = _get_meter()
        self.cpu_gauge = meter.create_gauge(
            name="system.cpu.utilization",
            description="Percentage of CPU utilization",
            unit="%",
        )
        self.memory_gauge = meter.create_gauge(
            name="system.memory.usage",
            description="Bytes of memory consumed",
            unit="By",
        )
        self.latency_histogram = meter.create_histogram(
            name="http.server.duration",
            description="Incoming request latency",
            unit="s",
        )

        # Internal mutable state
        self.tick_count = 0
        self.heap_leak_bytes = 0.0

    def tick(self) -> None:
        """
        Advance one simulation step.

        1. Compute CPU, memory, and latency values based on the incident
           preset and the current tick's anomaly probability draws.
        2. Write the values through the OTel instruments
           (system.cpu.utilization, system.memory.usage, http.server.duration).
        3. Record a Stratum Signal into self.capture for each metric so
           the Stratum pipeline can consume them.
        """
        self.tick_count += 1

        # ── Base CPU load with a gentle diurnal sinusoid ────────────────
        base_load = self.preset.get("base_cpu_mean", 35.0) + (
            math.sin(self.tick_count / 30.0) * 8.0
        )

        # ── CPU ─────────────────────────────────────────────────────────
        spike_prob = self.preset.get("cpu_spike_probability", 0.05)
        if self._rng.random() < spike_prob:
            cpu = self._rng.uniform(
                self.preset.get("cpu_spike_min", 88.0),
                self.preset.get("cpu_spike_max", 99.1),
            )
            status = "503"
        else:
            cpu = max(0.0, min(100.0, base_load + self._rng.uniform(-4.0, 4.0)))
            status = "200"
        cpu = round(cpu, 2)

        attrs = {"service.name": self.service_name, "http.status_code": status}
        self.cpu_gauge.set(cpu, attributes=attrs)
        self.capture.record(
            "cpu_usage", cpu, "%", extra_tags={"http.status_code": status}
        )

        # ── Memory ──────────────────────────────────────────────────────
        base_mem_mb = 256.0
        if self.preset.get("memory_leak_enabled", False):
            leak_range = self.preset.get(
                "memory_leak_per_tick_bytes", (500_000, 1_500_000)
            )
            self.heap_leak_bytes += self._rng.uniform(*leak_range)
        memory_bytes = int(
            (base_mem_mb * 1024 * 1024)
            + self.heap_leak_bytes
            + self._rng.uniform(-100_000, 100_000)
        )

        self.memory_gauge.set(memory_bytes, attributes=attrs)
        self.capture.record("memory_usage", memory_bytes, "By")

        # ── Latency ─────────────────────────────────────────────────────
        cpu_spiking = cpu > 85.0
        latency_degraded = self._rng.random() < self.preset.get(
            "latency_spike_probability", 0.03
        )
        if cpu_spiking or latency_degraded:
            degradation = self.preset.get("latency_degradation_range", (2.5, 6.2))
            latency_s = self._rng.uniform(*degradation)
        else:
            latency_s = self._rng.lognormvariate(math.log(0.08), 0.2)
        latency_s = round(latency_s, 4)

        self.latency_histogram.record(latency_s, attributes=attrs)
        self.capture.record("latency_p99", latency_s, "s")


# ── Public API ──────────────────────────────────────────────────────────

def generate_incident_signals(
    incident_type: str = "cpu_spike",
    service_name: str = "payment-api",
    duration_seconds: int = 30,
    tick_interval_seconds: int = 1,
    seed: int = 42,
) -> list[Signal]:
    """
    Generate SRE signals for a named incident type via OTel SDK.

    Supported incident_type values:
        "cpu_spike", "memory_leak", "latency_degradation", "normal"

    Each tick:
    - A CPU, memory, and latency value are computed using the incident
      preset's anomaly probabilities.
    - The values are written through the official OTel instruments
      (system.cpu.utilization gauge, system.memory.usage gauge,
       http.server.duration histogram).
    - A Stratum Signal is captured for each metric.

    Returns:
        list[Signal] — chronologically ordered signals (1 tick = 3 signals:
        cpu_usage, memory_usage, latency_p99).
    """
    if incident_type not in INCIDENT_PRESETS:
        logger.warning(
            "Unknown incident_type '%s', falling back to 'normal'", incident_type
        )
        incident_type = "normal"

    capture = _SignalCapture(service_name=service_name)
    sim = OTelPipelineSimulator(
        capture=capture,
        service_name=service_name,
        incident_type=incident_type,
        seed=seed,
    )

    num_ticks = max(1, duration_seconds // tick_interval_seconds)
    for _ in range(num_ticks):
        sim.tick()
        # Brief yield so the OTel SDK collector thread can run if it
        # needs to — not strictly required for the capture path, but
        # matches real-world pipeline timing.
        time.sleep(0.005)

    return capture.signals()


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
    signals: list[Signal] = []
    if isinstance(raw_data,str):
        try:
            raw_data = json.loads(raw_data)
            print("Successfully parsed JSON data.")
            
        except json.JSONDecodeError as e:
            return []

        try:
            if isinstance(raw_data,str) and not raw_data.endswith(".csv"):
                df = pd.read_csv(io.StringIO(raw_data))
            else:
                df = pd.read_csv(raw_data)
            print(f"Successfully loaded {len(df)} rows.")
            
            missing_count = df.isnull().sum().sum()
            if missing_count > 0:
                print(f"Warning: Found {missing_count} missing values.")
            
        except Exception as e:
            print(f"Error reading CSV: {e}")
            return None
    return signals


        
