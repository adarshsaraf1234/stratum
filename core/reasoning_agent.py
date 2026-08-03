"""
stratum/core/reasoning_agent.py

ReasoningAgent wraps an LLM and a DomainAdapter to produce structured
decisions from raw signals. This is the orchestration layer.
"""

import json
import logging
from typing import Any, Optional

from stratum.core.base_adapter import DomainAdapter
from stratum.core.schemas import StructuredDecision
from stratum.llm.base import BaseLLM

logger = logging.getLogger(__name__)


class ReasoningAgent:
    """
    Orchestrates the full pipeline:
        raw_data → parse_signals → build_state → build_prompt
                 → llm.generate → parse_output → StructuredDecision

    Usage:
        agent = ReasoningAgent(adapter=sre_adapter, llm=ollama_llm)
        decision = agent.reason(raw_data)
    """

    def __init__(
        self,
        adapter: DomainAdapter,
        llm: BaseLLM,
        max_retries: int = 2,
    ):
        """
        Args:
            adapter: A DomainAdapter implementation (SRE, Markets, ...)
            llm: A BaseLLM implementation (Ollama, OpenAI, ...)
            max_retries: Number of retry attempts if LLM call fails
        """
        self.adapter = adapter
        self.llm = llm
        self.max_retries = max_retries

    def reason(self, raw_data: Any) -> StructuredDecision:
        """
        Full pipeline: signals → state → prompt → LLM → decision.

        Steps to implement:
        1. Parse raw_data into signals via self.adapter.parse_signals()
        2. Build TemporalContext via self.adapter.build_state(signals)
        3. Build prompt via self.adapter.build_prompt(context)
        4. Call self.llm.generate(prompt) inside a retry loop
        5. Parse the response via self.adapter.parse_output(llm_response)
        6. Construct and return a StructuredDecision

        Handle failure cases:
        - If all retries fail, return a StructuredDecision with
          analysis="Error: ...", confidence=0.0, empty actions.
        - Log each stage with logger.info/debug for traceability.

        Returns:
            StructuredDecision
        """
        ...

    def reason_with_trace(self, raw_data: Any) -> tuple[StructuredDecision, dict]:
        """
        Like reason(), but also returns intermediate state for debugging.

        Use this for the demo UI and API trace endpoints.

        Returns:
            (decision, trace) where trace is a dict containing:
                {
                    "signal_count": int,
                    "context": dict,          # TemporalContext as JSON
                    "prompt": str,            # the exact LLM prompt
                    "llm_response": str,      # the raw LLM response
                }
        """
        ...