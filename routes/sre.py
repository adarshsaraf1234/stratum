"""
stratum/routes/sre.py

FastAPI route handlers for the SRE domain.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from stratum.data.sre.scenarios import SRE_SCENARIOS, get_scenario, generate_scenario_signals

logger = logging.getLogger(__name__)

router = APIRouter()


def get_sre_agent(request):
    """
    Extract the SRE ReasoningAgent from the FastAPI app state.

    Usage with Depends:
        agent = Depends(get_sre_agent)

    Steps to implement:
    1. Access request.app.state.sre_agent
    2. Return it
    """
    ...


@router.get("/scenarios")
def list_sre_scenarios() -> list[dict]:
    """
    Return metadata about all available SRE demo scenarios.

    Steps to implement:
    1. For each name in SRE_SCENARIOS, build a dict:
       {"name": name, "description": config["description"]}
    2. Return the list

    Returns:
        list[dict] — e.g.
        [
            {"name": "cpu_spike", "description": "CPU usage spikes to 95%+..."},
            ...
        ]
    """
    ...


@router.post("/analyze")
def analyze_sre(
    scenario: Optional[str] = None,
    raw_data: Optional[dict] = None,
    agent=Depends(get_sre_agent),
) -> dict:
    """
    Run the SRE reasoning pipeline and return the structured decision.

    Steps to implement:
    1. Input validation:
       - If raw_data is provided, use it directly
       - Elif scenario is provided, generate signals via
         generate_scenario_signals(scenario)
       - Else raise HTTPException(400, "Provide `scenario` or `raw_data`")
    2. Call agent.reason(raw_data or signals)
    3. Return dict(decision) — the StructuredDecision as a dict

    Returns:
        dict — the StructuredDecision fields:
               domain, analysis, confidence, suggested_actions,
               reasoning_trace, raw_llm_response
    """
    ...


@router.post("/analyze/trace")
def analyze_sre_trace(
    scenario: Optional[str] = None,
    raw_data: Optional[dict] = None,
    agent=Depends(get_sre_agent),
) -> dict:
    """
    Run the SRE pipeline and return both the decision AND full reasoning trace.

    Steps to implement:
    1. Same input validation as analyze_sre
    2. Call agent.reason_with_trace(...)
    3. Return {"decision": dict(decision), "trace": trace}

    Use this endpoint for the Streamlit demo panel that shows the
    intermediate TemporalContext and exact LLM prompt.

    Returns:
        dict — {"decision": ..., "trace": ...}
    """
    ...