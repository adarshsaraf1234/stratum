"""
stratum/adapters/sre/output.py

SRE output schemas and LLM prompt builder for Root Cause Analysis (RCA).
"""

import json
import logging
import re
from typing import Any, Optional

from stratum.core.schemas import Signal, StructuredDecision
from stratum.core.temporal_context import TemporalContext
from stratum.core.base_adapter import DomainAdapter
from stratum.adapters.sre.state import SREStateBuilder
from stratum.adapters.sre.signals import parse_sre_signals

logger = logging.getLogger(__name__)


class RCADecision(StructuredDecision):
    """
    The LLM's structured RCA output for an SRE incident.

    Extends StructuredDecision with SRE-specific fields.
    These extra fields are populated from the parsed LLM response:
        root_cause:       str  — what actually caused the incident
        severity:         str  — "low" | "medium" | "high" | "critical"
        affected_services: list[str] — which services are impacted
        remediation_steps: list[str] — ordered steps to resolve
        evidence:         list[str] — signals/metrics that support the conclusion

    The base class already provides:
        analysis, confidence, suggested_actions, reasoning_trace, raw_llm_response
    """
    root_cause: str = ""
    severity: str = "medium"
    affected_services: list[str] = []
    remediation_steps: list[str] = []
    evidence: list[str] = []


class SREAdapter(DomainAdapter):
    """
    SRE domain adapter — implements the DomainAdapter contract.

    Wires together:
        parse_signals()  → parse_sre_signals() from signals.py
        build_state()    → SREStateBuilder from state.py
        build_prompt()   → SREPromptBuilder logic below
        parse_output()   → parse_sre_output() logic below

    Usage:
        adapter = SREAdapter()
        agent = ReasoningAgent(adapter=adapter, llm=ollama_llm)
        decision = agent.reason(raw_data)
    """

    def __init__(self):
        self.state_builder = SREStateBuilder()

    def domain_name(self) -> str:
        """
        Return "sre".
        """
        return "sre"

    def parse_signals(self, raw_data: Any) -> list:
        """
        Convert raw input into Signal objects.

        - If raw_data is already a list of Signal objects (e.g. from the
          OTel simulator), pass it through directly.
        - Otherwise delegate to parse_sre_signals() for raw dicts,
          JSON strings, or CSV input.
        """
        if isinstance(raw_data, list) and all(
            isinstance(item, Signal) for item in raw_data
        ):
            return raw_data
        return parse_sre_signals(raw_data)

    def build_state(self, signals: list) -> TemporalContext:
        """
        Delegate to self.state_builder.build_state(signals).
        """
        return self.state_builder.build_state(signals)

    def build_prompt(self, context: TemporalContext) -> str:
        # ── 1. System-style instruction ─────────────────────────────
        prompt = (
            "You are an SRE root cause analysis engine. Analyze the "
            "following system state and identify the root cause of the "
            "incident. Respond with JSON only.\n\n"
        )

        # ── 2. TemporalContext serialized as JSON ───────────────────
        context_json = json.dumps(context.dict(), indent=2, default=str)
        prompt += "=== SYSTEM STATE ===\n"
        prompt += context_json + "\n\n"

        # ── 3. Plain-English summary (surfaced prominently) ─────────
        prompt += "=== SUMMARY ===\n"
        prompt += (
            context.summary if context.summary else "No summary available."
        )
        prompt += "\n\n"

        # ── 3.5. NEW: explicit instruction when no events detected ──
        if len(context.events) == 0:
            prompt += (
                "=== IMPORTANT ===\n"
                "No events were detected in this window. The system is "
                "healthy. Do NOT speculate about minor trend fluctuations "
                "as if they were incidents — small rises or falls in a "
                "metric with no detected event are normal noise, not a "
                "root cause. Your root_cause field MUST state that the "
                "system is healthy and no anomalies were found. Do not "
                "invent a cause.\n\n"
            )

        # ── 4. Expected output schema ───────────────────────────────
        prompt += (
            "=== EXPECTED OUTPUT ===\n"
            "Respond with a single JSON object in this exact format:\n"
            "{\n"
            '  "root_cause": "<string>",\n'
            '  "severity": "low|medium|high|critical",\n'
            '  "analysis": "<string>",\n'
            '  "confidence": "<float between 0.0 and 1.0>",\n'
            '  "affected_services": ["<string>"],\n'
            '  "remediation_steps": ["<string>"],\n'
            '  "evidence": ["<string>"],\n'
            '  "suggested_actions": ["<string>"]\n'
            "}\n\n"
        )

        # ── 5. Constraint emphasis ──────────────────────────────────
        prompt += (
            "Base your analysis ONLY on the provided context. "
            "Do not invent metrics or services."
        )

        return prompt

    def parse_output(self, llm_response: str) -> dict:
        """
        Parse the LLM's RCA response into a structured dict.

        Steps to implement:
        1. If llm_response starts with "ERROR:", return a default dict:
           {"analysis": llm_response, "confidence": 0.0,
            "suggested_actions": [], "root_cause": "Unknown"}
        2. Extract JSON from the response:
           - Try json.loads(response) directly
           - If that fails, extract the first {...} block via regex
        3. Map the JSON fields into the keys expected by ReasoningAgent:
           analysis, confidence, suggested_actions
           Plus SRE-specific: root_cause, severity, affected_services,
                              remediation_steps, evidence
        4. Provide sensible defaults for any missing field
        5. Clamp confidence to [0.0, 1.0]

        Returns:
            dict
        """
        # ── 1. Error passthrough ────────────────────────────────────
        if llm_response.startswith("ERROR:"):
            return {
                "analysis": llm_response,
                "confidence": 0.0,
                "suggested_actions": [],
                "root_cause": "Unknown",
            }

        # ── 2. Extract JSON from the response ───────────────────────
        data: Optional[dict] = None

        # Try a direct JSON parse first
        try:
            data = json.loads(llm_response)
        except (json.JSONDecodeError, TypeError):
            data = None

        # Fallback: extract the first {...} JSON block via regex
        if data is None:
            match = re.search(r"\{.*\}", llm_response, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    data = None

        # No JSON at all — return a safe default
        if data is None:
            logger.warning(
                "No JSON found in LLM response: %s", llm_response[:200]
            )
            return {
                "analysis": llm_response,
                "confidence": 0.0,
                "suggested_actions": [],
                "root_cause": "Unknown",
            }

        # ── 3 & 4. Map fields + defaults for missing keys ───────────
        def _as_list(value: Any) -> list[str]:
            if isinstance(value, list):
                return [str(item) for item in value]
            if isinstance(value, str) and value.strip():
                return [value]
            return []

        # Confidence may come back as a string — coerce safely
        try:
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0

        result = {
            "analysis": str(data.get("analysis", "")).strip(),
            "confidence": confidence,  # clamped below
            "suggested_actions": _as_list(data.get("suggested_actions")),
            "root_cause": str(data.get("root_cause", "Unknown")).strip(),
            "severity": str(data.get("severity", "medium")).strip(),
            "affected_services": _as_list(data.get("affected_services")),
            "remediation_steps": _as_list(data.get("remediation_steps")),
            "evidence": _as_list(data.get("evidence")),
        }

        # ── 5. Clamp confidence to [0.0, 1.0] ───────────────────────
        result["confidence"] = max(0.0, min(1.0, result["confidence"]))

        return result