"""
stratum/adapters/markets/signals.py

Markets signal ingestion — generates mock price/volume data simulating
stock/ETF behavior for demo scenarios.
"""

import math
import random
from datetime import datetime, timedelta
from typing import Any, Optional

from stratum.core.schemas import Signal


def generate_market_signals(
    scenario: str = "normal",
    ticker: str = "AAPL",
    start_time: Optional[datetime] = None,
    duration_minutes: int = 60,
    interval_seconds: int = 60,
    start_price: float = 150.0,
    seed: int = 42,
) -> list[Signal]:
    """
    Generate mock market signals for a given scenario.

    Supported scenario values:
        - "bull_run"       : Price trends up +5%, volume spikes high
        - "crash"          : Price drops 8%+, volume spikes sharply
        - "consolidation"  : Price ranges ±1%, volume stays low
        - "normal"         : Mild upward drift, average volume

    Steps to implement:
    1. Seed random for deterministic output
    2. Compute number of data points from duration & interval
    3. Walk through the window, computing price and volume at each step:
       - Use geometric brownian motion for price:
         price *= exp((drift - 0.5 * sigma^2) * dt + sigma * sqrt(dt) * z)
       - Volume scales with scenario (bull/crash = high, consolidation = low)
    4. For each timestamp, append 2 Signal objects:
       - name="price",  unit="USD"
       - name="volume", unit="shares"
       Each with tags={"ticker": ticker}

    Scenario parameters:
        bull_run:      drift=+0.0008/min,  sigma=0.002,  volume_mult=2.0
        crash:         drift=-0.0015/min,  sigma=0.004,  volume_mult=3.0
        consolidation: drift=0,            sigma=0.0005, volume_mult=0.5
        normal:        drift=+0.0001/min,  sigma=0.001,  volume_mult=1.0

    Round prices to 2 decimals, volumes to integers.

    Returns:
        list[Signal] — chronologically ordered price+volume stream
    """
    ...


def parse_market_signals(raw_data: Any) -> list[Signal]:
    """
    Convert raw market data (Yahoo Finance / Alpaca API / JSON) into Signal objects.

    Expected raw_data formats:
        - list[dict] with keys: timestamp, open/high/low/close, volume
        - dict with "candles" / "bars" / "signals" key containing the above
        - JSON string that parses into one of the above

    Steps to implement:
    1. Normalize to a list of dicts (unwrap "candles"/"bars" key if present)
    2. For each bar, extract:
       - timestamp: convert to datetime
       - price: use the "close" price (or the only price field available)
       - volume: numeric volume value
    3. Create Signal objects:
       - name="price",  value=close_price, unit="USD",
         tags={"ticker": ticker_or_unknown}
       - name="volume", value=volume,      unit="shares",
         tags={"ticker": ticker_or_unknown}
    4. Skip malformed bars with a warning log
    5. Sort by timestamp

    Returns:
        list[Signal]
    """
    ...