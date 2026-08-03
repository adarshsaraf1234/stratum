"""
stratum/data/markets/scenarios.py

Mock market demo scenarios — named configurations that
generate_market_signals() accepts. These are the scenarios users can
pick from in the demo UI / CLI.
"""

from stratum.adapters.markets.signals import generate_market_signals

# Each scenario maps to the generate_market_signals() parameters.
# Add new scenarios here to make them appear in the demo.
MARKET_SCENARIOS: dict[str, dict] = {
    "bull_run": {
        "description": "Price trends up +5% with elevated volume.",
        "scenario": "bull_run",
        "ticker": "AAPL",
        "duration_minutes": 60,
        "interval_seconds": 60,
        "start_price": 150.0,
    },
    "crash": {
        "description": "Price drops 8%+ with a sharp volume spike.",
        "scenario": "crash",
        "ticker": "TSLA",
        "duration_minutes": 60,
        "interval_seconds": 60,
        "start_price": 240.0,
    },
    "consolidation": {
        "description": "Price ranges within ±1%, low volume.",
        "scenario": "consolidation",
        "ticker": "MSFT",
        "duration_minutes": 60,
        "interval_seconds": 60,
        "start_price": 400.0,
    },
    "normal": {
        "description": "Mild upward drift with average volume.",
        "scenario": "normal",
        "ticker": "GOOGL",
        "duration_minutes": 60,
        "interval_seconds": 60,
        "start_price": 175.0,
    },
}


def get_scenario(name: str) -> dict:
    """
    Return the scenario config dict for a given name.

    Steps to implement:
    1. Look up name in MARKET_SCENARIOS
    2. If found, return the config dict
    3. If not found, raise KeyError with a helpful message
       listing available scenarios
    """
    ...


def list_scenarios() -> list[str]:
    """
    Return the names of all available market scenarios.

    Returns:
        list[str] — e.g. ["bull_run", "crash", ...]
    """
    ...


def generate_scenario_signals(scenario_name: str, **kwargs) -> list:
    """
    Generate signals for a named scenario.

    Convenience wrapper:
        config = get_scenario(scenario_name)
        signals = generate_market_signals(**config, **kwargs)

    Returns:
        list[Signal]
    """
    ...