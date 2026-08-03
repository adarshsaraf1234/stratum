"""
stratum/routes/markets.py

FastAPI route handlers for the Markets domain.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from stratum.data.markets.scenarios import (
    MARKET_SCENARIOS,
    get_scenario,
    generate_scenario_signals,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def get_market_agent(request):
    """
    Extract the Markets ReasoningAgent from the FastAPI app state.

    Usage with Depends:
        agent = Depends(get_market_agent)

    Steps to implement:
    1. Access request.app.state.market_agent
    2. Return it
    """
    ...


@router.get("/scenarios")
def list_market_scenarios() -> list[dict]:
    """
    Return metadata about all available market demo scenarios.

    Steps to implement:
    1. For each name in MARKET_SCENARIOS, build a dict:
       {"name": name, "description": config["description"]}
    2. Return the list

    Returns:
        list[dict] — e.g.
        [
            {"name": "bull_run", "description": "Price trends up +5%..."},
            ...
        ]
    """
    ...


@router.post("/analyze")
def analyze_market(
    scenario: Optional[str] = None,
    ticker: Optional[str] = None,
    raw_data: Optional[dict] = None,
    agent=Depends(get_market_agent),
) -> dict:
    """
    Run the Markets reasoning pipeline and return the structured decision.

    Steps to implement:
    1. Input validation:
       - If raw_data is provided, use it directly
       - Elif scenario is provided:
         - If ticker is also provided, override the scenario's ticker
         - Generate signals via generate_scenario_signals(scenario, ticker=...)
       - Else raise HTTPException(400, "Provide `scenario` or `raw_data`")
    2. Call agent.reason(signals)
    3. Return dict(decision) — the StructuredDecision as a dict

    Returns:
        dict — the StructuredDecision fields:
               domain, analysis, confidence, suggested_actions,
               reasoning_trace, raw_llm_response
    """
    ...


@router.post("/analyze/trace")
def analyze_market_trace(
    scenario: Optional[str] = None,
    ticker: Optional[str] = None,
    raw_data: Optional[dict] = None,
    agent=Depends(get_market_agent),
) -> dict:
    """
    Run the Markets pipeline and return both the decision AND full reasoning trace.

    Steps to implement:
    1. Same input validation as analyze_market
    2. Call agent.reason_with_trace(...)
    3. Return {"decision": dict(decision), "trace": trace}

    Use this endpoint for the Streamlit demo panel that shows the
    intermediate TemporalContext and exact LLM prompt.

    Returns:
        dict — {"decision": ..., "trace": ...}
    """
    ...