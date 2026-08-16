"""
stratum/data/sre/scenarios.py

Mock SRE demo scenarios — named configurations that generate_incident_signals()
accepts. These are the scenarios users can pick from in the demo UI / CLI.
"""

from stratum.adapters.sre.signals import generate_incident_signals

# Each scenario maps to the generate_incident_signals() parameters.
# The generator now runs through the OpenTelemetry SDK with per-tick
# probability-based anomaly injection (not artificial mid-window spikes).
# Add new scenarios here to make them appear in the demo.
SRE_SCENARIOS: dict[str, dict] = {
    "cpu_spike": {
        "description": "Sustained CPU saturation (180+ ticks) peaking at 99%.",
        "incident_type": "cpu_spike",
        "duration_seconds": 240,
        "tick_interval_seconds": 1,
    },
    "memory_leak": {
        "description": "Heap leak of ~10-20 MB per tick after a 60-tick grace period.",
        "incident_type": "memory_leak",
        "duration_seconds": 150,
        "tick_interval_seconds": 1,
    },
    "latency_degradation": {
        "description": "Latency spikes with 30% probability, P99 degrades to 2.5-6.2s.",
        "incident_type": "latency_degradation",
        "duration_seconds": 60,
        "tick_interval_seconds": 1,
    },
    "normal": {
        "description": "Healthy bounds — <1% anomaly probability.",
        "incident_type": "normal",
        "duration_seconds": 60,
        "tick_interval_seconds": 1,
    },
}


def get_scenario(name: str) -> dict:
    """
    Return the scenario config dict for a given name.

    Steps to implement:
    1. Look up name in SRE_SCENARIOS
    2. If found, return the config dict
    3. If not found, raise KeyError with a helpful message
       listing available scenarios
    """
    if name in SRE_SCENARIOS:
        return SRE_SCENARIOS[name]
    else:
        available = ', '.join(SRE_SCENARIOS.keys())
        raise KeyError(f"Scenario '{name}' not found. Available scenarios: {available}")


def list_scenarios() -> list[str]:
    """
    Return the names of all available SRE scenarios.

    Returns:
        list[str] — e.g. ["cpu_spike", "memory_leak", ...]
    """
    return list(SRE_SCENARIOS.keys())


def generate_scenario_signals(scenario_name: str, **kwargs) -> list:
    """
    Generate signals for a named scenario.

    Convenience wrapper:
        config = get_scenario(scenario_name)
        signals = generate_incident_signals(**config, **kwargs)

    Returns:
        list[Signal]
    """
    config = get_scenario(scenario_name)
    # Strip non-generator keys (e.g. "description") — only the
    # generate_incident_signals() parameters should be forwarded.
    generator_keys = {
        "incident_type",
        "service_name",
        "duration_seconds",
        "tick_interval_seconds",
        "seed",
    }
    params = {k: v for k, v in config.items() if k in generator_keys}
    # kwargs override scenario defaults (e.g. duration_seconds=300)
    params.update(kwargs)
    return generate_incident_signals(**params)
