"""
stratum/data/sre/scenarios.py

Mock SRE demo scenarios — named configurations that generate_incident_signals()
accepts. These are the scenarios users can pick from in the demo UI / CLI.
"""

from stratum.adapters.sre.signals import generate_incident_signals

# Each scenario maps to the generate_incident_signals() parameters.
# Add new scenarios here to make them appear in the demo.
SRE_SCENARIOS: dict[str, dict] = {
    "cpu_spike": {
        "description": "CPU usage spikes to 95%+ mid-window, then recovers.",
        "incident_type": "cpu_spike",
        "duration_minutes": 30,
        "interval_seconds": 30,
    },
    "memory_leak": {
        "description": "Memory usage grows linearly from 50% to 95%.",
        "incident_type": "memory_leak",
        "duration_minutes": 45,
        "interval_seconds": 30,
    },
    "latency_degradation": {
        "description": "P99 latency climbs from 100ms to 2000ms.",
        "incident_type": "latency_degradation",
        "duration_minutes": 30,
        "interval_seconds": 30,
    },
    "normal": {
        "description": "All metrics within healthy bounds. No incident.",
        "incident_type": "normal",
        "duration_minutes": 30,
        "interval_seconds": 30,
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
    ...


def list_scenarios() -> list[str]:
    """
    Return the names of all available SRE scenarios.

    Returns:
        list[str] — e.g. ["cpu_spike", "memory_leak", ...]
    """
    ...


def generate_scenario_signals(scenario_name: str, **kwargs) -> list:
    """
    Generate signals for a named scenario.

    Convenience wrapper:
        config = get_scenario(scenario_name)
        signals = generate_incident_signals(**config, **kwargs)

    Returns:
        list[Signal]
    """
    ...