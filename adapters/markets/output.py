"""
stratum/adapters/markets/output.py

Markets output schemas and LLM prompt builder for signal reports.
"""

import json
import logging
from typing import Any, Optional

from stratum.core.schemas import StructuredDecision
from stratum.core.temporal_context import TemporalContext
from stratum.core.base_adapter import DomainAdapter
from stratum.adapters.markets.state import MarketStateBuilder
from stratum.adapters.markets.signals import parse_market_signals

logger = logging.getLogger(__name__)


class SignalReport(StructuredDecision):
    """
    The LLM's structured signal report for a market scenario.

    Extends StructuredDecision with Markets-specific fields.
    These extra fields are populated from the parsed LLM response:
        regime:            str   — "bull" | "bear" | "ranging" | "crash"
        signal_strength:   str   — "strong" | "moderate" | "weak"
        price_target_range: list[float] — [lower_bound, upper_bound]
        key_levels:         list[float] — support/resistance levels
        volume_analysis:    str   — assessment of volume behavior

    The base class already provides:
        analysis, confidence, suggested_actions, reasoning_trace, raw_llm_response
    """
    regime: str = "ranging"
    signal_strength: str = "weak"
    price_target_range: list[float] = []
    key_levels: list[float] = []
    volume_analysis: str = ""


class MarketAdapter(DomainAdapter):
    """
    Markets domain adapter — implements the DomainAdapter contract.

    Wires together:
        parse_signals()  → parse_market_signals() from signals.py
        build_state()    → MarketStateBuilder from state.py
        build_prompt()   → prompt builder logic below
        parse_output()   → parse_market_output() logic below

    Usage:
        adapter = MarketAdapter()
        agent = ReasoningAgent(adapter=adapter, llm=ollama_llm)
        decision = agent.reason(raw_data)
    """

    def __init__(self):
        self.state_builder = MarketStateBuilder()

    def domain_name(self) -> str:
        """
        Return "markets".
        """
        return "markets"

    def parse_signals(self, raw_data: Any) -> list:
        """
        Delegate to parse_market_signals(raw_data) from signals.py.
        """
        ...

    def build_state(self, signals: list) -> TemporalContext:
        """
        Delegate to self.state_builder.build_state(signals).
        """
        ...

    def build_prompt(self, context: TemporalContext) -> str:
        """
        Build the signal report prompt for the LLM.

        Steps to implement:
        1. Start with a system-style instruction:
           "You are a financial markets analyst. Analyze the following
            market state and produce a structured signal report.
            Respond with JSON only."
        2. Include the TemporalContext serialized as JSON
           (use context.model_dump(mode="json"))
        3. Include the summary string (ticker, trend, events)
        4. Specify expected output schema:
           {
             "regime": "bull"|"bear"|"ranging"|"crash",
             "analysis": str,
             "confidence": float,
             "signal_strength": "strong"|"moderate"|"weak",
             "price_target_range": [float, float],
             "key_levels": [float],
             "volume_analysis": str,
             "suggested_actions": [str]
           }
        5. Emphasize: "Base your analysis ONLY on the provided context.
           This is for educational purposes — do not give financial advice."

        Returns:
            str
        """
        ...

    def parse_output(self, llm_response: str) -> dict:
        """
        Parse the LLM's signal report response into a structured dict.

        Steps to implement:
        1. If llm_response starts with "ERROR:", return a default dict:
           {"analysis": llm_response, "confidence": 0.0,
            "suggested_actions": [], "regime": "unknown"}
        2. Extract JSON from the response:
           - Try json.loads(response) directly
           - If that fails, extract the first {...} block via regex
        3. Map the JSON fields into the keys expected by ReasoningAgent:
           analysis, confidence, suggested_actions
           Plus Markets-specific: regime, signal_strength,
                                  price_target_range, key_levels, volume_analysis
        4. Provide sensible defaults for any missing field
        5. Clamp confidence to [0.0, 1.0]
        6. Validate regime is one of: bull|bear|ranging|crash
           (fall back to "ranging" if invalid)

        Returns:
            dict
        """
        ...