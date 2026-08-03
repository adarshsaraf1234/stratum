"""
stratum/core/base_adapter.py

Abstract adapter interface that all domain adapters (SRE, Markets, etc.)
must implement. Defines the contract between domain-specific logic and the
Stratum core framework.
"""

from abc import ABC, abstractmethod
from typing import Any

from stratum.core.temporal_context import TemporalContext
from stratum.core.schemas import Signal


class DomainAdapter(ABC):
    """
    Abstract interface for domain adapters.

    Every adapter must implement these 4 methods to plug into the framework:
      1. parse_signals()  — Convert raw data into list[Signal]
      2. build_state()    — Convert list[Signal] into TemporalContext
      3. build_prompt()   — Convert TemporalContext into LLM prompt string
      4. parse_output()   — Parse LLM response into structured dict
    """

    @abstractmethod
    def domain_name(self) -> str:
        """
        Return the domain name, e.g. "sre" or "markets".
        Used as an identifier throughout the framework.
        """
        ...

    @abstractmethod
    def parse_signals(self, raw_data: Any) -> list[Signal]:
        """
        Convert raw input data (JSON, CSV, dict, list of dicts) into a
        list of normalized Signal objects.

        Steps to implement:
        - Inspect the structure of raw_data (dict key names, formats)
        - Extract timestamp, metric name, value, unit, and tags
        - Handle missing/invalid fields gracefully
        - Return an empty list if nothing is parseable

        Returns:
            list[Signal]
        """
        ...

    @abstractmethod
    def build_state(self, signals: list[Signal]) -> TemporalContext:
        """
        Convert a list of Signals into a TemporalContext.

        This is where ALL deterministic logic lives:
        - Trend computation  (linear regression slope per signal)
        - Event detection    (threshold breaches, anomalies)
        - Segment detection  (change points / rolling variance)
        - Periodicity        (FFT / cycle detection, optional)
        - Summary generation (plain-English overview)

        Returns:
            TemporalContext
        """
        ...

    @abstractmethod
    def build_prompt(self, context: TemporalContext) -> str:
        """
        Build the LLM prompt string from a TemporalContext.

        The prompt MUST include:
        - The domain name and role instructions
        - The structured context (events, trend, segments, summary)
        - What to reason about (root cause / regime detection / etc.)
        - The expected JSON output format

        Returns:
            str — the complete prompt
        """
        ...

    @abstractmethod
    def parse_output(self, llm_response: str) -> dict:
        """
        Parse the LLM's raw text response into a structured dict.

        Should extract (at minimum):
            analysis: str
            confidence: float (0.0 - 1.0)
            suggested_actions: list[str]
            reasoning_trace: str (optional)

        Handles common failure modes:
        - LLM returns prose around a JSON block  → extract the JSON
        - LLM returns invalid JSON               → best-effort regex extraction
        - LLM returns empty response             → return default dict

        Returns:
            dict with keys: analysis, confidence, suggested_actions, ...
        """
        ...