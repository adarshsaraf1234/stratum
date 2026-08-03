"""
stratum/adapters/sre/output.py

SRE output schemas and LLM prompt builder for Root Cause Analysis (RCA).
"""

import json
import logging
from typing import Any, Optional

from stratum.core.schemas import StructuredDecision
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
        ...

    def parse_signals(self, raw_data: Any) -> list:
        """
        Delegate to parse_sre_signals(raw_data) from signals.py.
        """
        ...

    def build_state(self, signals: list) -> TemporalContext:
        """
        Delegate to self.state_builder.build_state(signals).
        """
        ...

    def build_prompt(self, context: TemporalContext) -> str:
        """
        Build the RCA prompt for the LLM.

        Steps to implement:
        1. Start with a system-style instruction:
           "You are an SRE root cause analysis engine. Analyze the
            following system state and identify the root cause of the
            incident. Respond with JSON only."
        2. Include the TemporalContext serialized as JSON
           (use context.model_dump(mode="json"))
        3. Include the summary string
        4. Specify expected output schema:
           {
             "root_cause": str,
             "severity": "low"|"medium"|"high"|"critical",
             "analysis": str,
             "confidence": float,
             "affected_services": [str],
             "remediation_steps": [str],
             "evidence": [str],
             "suggested_actions": [str]
           }
        5. Emphasize: "Base your analysis ONLY on the provided context.
           Do not invent metrics or services."

        Returns:
            str
        """
        ...

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
        ...