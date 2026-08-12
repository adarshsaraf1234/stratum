"""
stratum/core/reasoning_agent.py

ReasoningAgent wraps an LLM and a DomainAdapter to produce structured
decisions from raw signals. This is the orchestration layer.
"""

import json
import logging
from typing import Any

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

    def _call_llm(self, prompt: str) -> str:
        """
        Call the LLM with retries, returning the first valid response.

        A valid response is any string that does NOT start with "ERROR:"
        (the BaseLLM error contract — generate() never raises, it returns
        an "ERROR: ..." string instead). Exceptions are also treated as a
        failed attempt for extra safety.

        Returns:
            str — the response, or "" if all attempts failed.
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.llm.generate(prompt)
            except Exception as exc:  # defensive — BaseLLM shouldn't raise
                logger.warning(
                    "LLM call raised on attempt %d/%d: %s",
                    attempt,
                    self.max_retries,
                    exc,
                )
                continue

            if response.startswith("ERROR:"):
                logger.warning(
                    "LLM returned error on attempt %d/%d: %s",
                    attempt,
                    self.max_retries,
                    response[:120],
                )
                continue

            return response

        logger.error("All %d LLM attempts failed.", self.max_retries)
        return ""

    def _build_decision(
        self, decision_data: dict, llm_response: str
    ) -> StructuredDecision:
        """
        Construct a StructuredDecision from the adapter's parsed dict.

        Maps the universal keys (analysis, confidence, suggested_actions)
        into the base schema. Domain-specific extras (e.g. root_cause,
        severity, remediation_steps for SRE) are preserved by serializing
        the full parsed dict into reasoning_trace.
        """
        return StructuredDecision(
            domain=self.adapter.domain_name(),
            analysis=str(decision_data.get("analysis", "")),
            confidence=float(decision_data.get("confidence", 0.0)),
            suggested_actions=list(decision_data.get("suggested_actions", [])),
            reasoning_trace=json.dumps(decision_data, default=str),
            raw_llm_response=llm_response,
        )

    def _error_decision(self, llm_response: str = "") -> StructuredDecision:
        """Build an error StructuredDecision after all retries are exhausted."""
        return StructuredDecision(
            domain=self.adapter.domain_name(),
            analysis=(
                f"Error: LLM call failed after {self.max_retries} attempts."
            ),
            confidence=0.0,
            suggested_actions=[],
            reasoning_trace="",
            raw_llm_response=llm_response,
        )

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
        signals = self.adapter.parse_signals(raw_data)
        context = self.adapter.build_state(signals)
        prompt = self.adapter.build_prompt(context)

        logger.info(
            "Parsed %d signals → TemporalContext (%d events, %d segment(s))",
            len(signals),
            context.event_count,
            len(context.segments),
        )
        logger.debug("TemporalContext summary: %s", context.summary)

        llm_response = self._call_llm(prompt)
        if not llm_response:
            return self._error_decision()

        logger.info("Received LLM response (%d chars)", len(llm_response))
        decision_data = self.adapter.parse_output(llm_response)
        logger.info(
            "Parsed structured decision (confidence=%.2f)",
            decision_data.get("confidence", 0.0),
        )

        return self._build_decision(decision_data, llm_response)

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
        signals = self.adapter.parse_signals(raw_data)
        context = self.adapter.build_state(signals)
        prompt = self.adapter.build_prompt(context)

        llm_response = self._call_llm(prompt)

        trace = {
            "signal_count": len(signals),
            "context": context.dict(),
            "prompt": prompt,
            "llm_response": llm_response,
        }

        if not llm_response:
            return self._error_decision(), trace

        decision_data = self.adapter.parse_output(llm_response)
        decision = self._build_decision(decision_data, llm_response)
        return decision, trace