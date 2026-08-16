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
from datetime import datetime, timedelta
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
        timestamp: Optional[datetime] = None,
    ) -> None:
        self._signals.append(
            Signal(
                timestamp=timestamp or datetime.now(),
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
        "cpu_saturation_probability": 0.02,   # ~19% chance per 60-tick window
        "cpu_saturation_start_tick": 30,      # guaranteed saturation at tick 30
        "cpu_saturation_duration_ticks": 180,
        "cpu_spike_min": 88.0,
        "cpu_spike_max": 99.1,
        "base_cpu_mean": 30.0,
        "base_load_amplitude": 8.0,
        "base_load_noise": 4.0,
        "memory_leak_enabled": False,
        "latency_spike_probability": 0.05,
    },
    "memory_leak": {
        "cpu_saturation_probability": 0.003,  # keep CPU mostly healthy
        "base_cpu_mean": 40.0,
        "base_load_amplitude": 2.0,
        "base_load_noise": 4.0,
        "memory_leak_enabled": True,
        "memory_leak_grace_ticks": 60,
        "memory_leak_per_tick_bytes": (2_000_000, 5_000_000),
        "latency_spike_probability": 0.03,
    },
    "latency_degradation": {
        "cpu_saturation_probability": 0.001,  # don't let CPU dominate this scenario
        "base_cpu_mean": 50.0,
        "base_load_amplitude": 2.0,
        "base_load_noise": 4.0,
        "memory_leak_enabled": False,
        "latency_spike_probability": 0.30,
        "latency_degradation_range": (2.5, 6.2),
    },
    "normal": {
        "cpu_saturation_probability": 0.0,    # truly quiet
        "base_cpu_mean": 35.0,
        "base_load_amplitude": 0.0,           # zero drift — no false trends
        "base_load_noise": 1.0,               # tiny walk — max ~5.7% drift
        "memory_leak_enabled": False,
        "latency_spike_probability": 0.0,     # zero latency anomalies
        "latency_sigma": 0.10,
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
        tick_interval_seconds: int = 1,
        seed: int = 42,
    ):
        self.capture = capture
        self.service_name = service_name
        self.incident_type = incident_type
        self.tick_interval_seconds = tick_interval_seconds
        self.preset = INCIDENT_PRESETS.get(incident_type, INCIDENT_PRESETS["normal"])

        # Simulated clock — timestamps advance by tick_interval_seconds per
        # tick, NOT wall-clock time. This keeps the deterministic state
        # builder's duration-based checks (e.g. BREACH_DURATION_SECONDS)
        # meaningful: a 180-tick saturation spans 180 simulated seconds.
        self._start_time = datetime.now()

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
        # Sustained CPU saturation: ticks remaining in the current
        # saturation event (a real incident stays saturated, it doesn't
        # flicker). 0 means "not currently saturating".
        self._cpu_saturation_remaining = 0

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

        # Simulated timestamp for this tick — matches the configured
        # tick interval so window durations are meaningful to downstream
        # deterministic logic.
        sim_ts = self._start_time + timedelta(
            seconds=(self.tick_count - 1) * self.tick_interval_seconds
        )

        # ── Base CPU load with a gentle diurnal sinusoid ────────────────
        # Amplitude is preset-configurable: incident scenarios allow mild
        # drift, but "normal" sets it to 0 so the only variation is the ±4
        # random walk — preventing false trend events.
        base_load = self.preset.get("base_cpu_mean", 35.0) + (
            math.sin(self.tick_count / 30.0)
            * self.preset.get("base_load_amplitude", 8.0)
        )

        # ── CPU ─────────────────────────────────────────────────────────
        # Real incidents saturate and STAY saturated (180+ ticks), rather
        # than flickering on/off. Once a saturation event starts, remaining
        # ticks stay above the threshold until the duration elapses.
        # A preset may force a guaranteed saturation start tick so every
        # run definitely exhibits the incident (deterministic benchmarks).
        force_start = (
            self.preset.get("cpu_saturation_start_tick", 0)
            and self.tick_count == self.preset["cpu_saturation_start_tick"]
        )
        if self._cpu_saturation_remaining > 0:
            # Mid-saturation: keep CPU pinned high, 88-99%
            cpu = self._rng.uniform(
                self.preset.get("cpu_spike_min", 88.0),
                self.preset.get("cpu_spike_max", 99.1),
            )
            status = "503"
            self._cpu_saturation_remaining -= 1
        elif force_start or self._rng.random() < self.preset.get(
            "cpu_saturation_probability", 0.05
        ):
            # Start a new saturation event
            sat_ticks = self.preset.get("cpu_saturation_duration_ticks", 180)
            self._cpu_saturation_remaining = sat_ticks - 1
            cpu = self._rng.uniform(
                self.preset.get("cpu_spike_min", 88.0),
                self.preset.get("cpu_spike_max", 99.1),
            )
            status = "503"
        else:
            noise = self.preset.get("base_load_noise", 4.0)
            cpu = max(0.0, min(100.0, base_load + self._rng.uniform(-noise, noise)))
            status = "200"
        cpu = round(cpu, 2)

        attrs = {"service.name": self.service_name, "http.status_code": status}
        self.cpu_gauge.set(cpu, attributes=attrs)
        self.capture.record(
            "cpu_usage",
            cpu,
            "%",
            extra_tags={"http.status_code": status},
            timestamp=sim_ts,
        )

        # ── Memory ──────────────────────────────────────────────────────
        base_mem_mb = 256.0
        # Only leak after the grace period elapses — gives a 1-2 minute
        # healthy baseline before the leak begins, closer to real incidents.
        leak_grace_ticks = self.preset.get("memory_leak_grace_ticks", 60)
        if (
            self.preset.get("memory_leak_enabled", False)
            and self.tick_count > leak_grace_ticks
        ):
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
        self.capture.record("memory_usage", memory_bytes, "By", timestamp=sim_ts)

        # ── Latency ─────────────────────────────────────────────────────
        cpu_spiking = cpu > 85.0
        latency_degraded = self._rng.random() < self.preset.get(
            "latency_spike_probability", 0.03
        )
        if cpu_spiking or latency_degraded:
            degradation = self.preset.get("latency_degradation_range", (2.5, 6.2))
            latency_s = self._rng.uniform(*degradation)
        else:
            # Baseline latency — normal presets can shrink the lognormal
            # sigma to reduce false-positive spike events.
            sigma = self.preset.get(
                "latency_sigma", 0.2
            )
            latency_s = self._rng.lognormvariate(math.log(0.08), sigma)
        latency_s = round(latency_s, 4)

        self.latency_histogram.record(latency_s, attributes=attrs)
        self.capture.record("latency_p99", latency_s, "s", timestamp=sim_ts)


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
        tick_interval_seconds=tick_interval_seconds,
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


        
