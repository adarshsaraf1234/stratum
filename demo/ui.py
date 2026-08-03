"""
stratum/demo/ui.py

Streamlit demo application — 4-panel layout showing the full pipeline:
decision output, TemporalContext state, and reasoning trace.
"""

import json
import logging
from typing import Optional

import streamlit as st

from stratum.data.sre.scenarios import generate_scenario_signals as gen_sre
from stratum.data.markets.scenarios import generate_scenario_signals as gen_market
from stratum.data.sre.scenarios import SRE_SCENARIOS
from stratum.data.markets.scenarios import MARKET_SCENARIOS

logger = logging.getLogger(__name__)


# Cache the ReasoningAgents so we don't rebuild them on every rerun.
@st.cache_resource
def get_agents():
    """
    Build and return the SRE + Market ReasoningAgents.

    Steps to implement:
    1. Create OllamaLLM(model="llama3")  (or allow env override)
    2. Create SREAdapter() and MarketAdapter()
    3. Create ReasoningAgent for each
    4. Return both agents

    Returns:
        (sre_agent, market_agent)
    """
    ...


def render_decision_panel(decision):
    """
    Render the StructuredDecision as the main output panel.

    Steps to implement:
    1. st.subheader(f"ℹ️ {decision.domain.upper()} Analysis")
    2. st.write(decision.analysis)
    3. Confidence: colored progress bar
       - green if >= 0.7, yellow if >= 0.4, red otherwise
       - st.progress(decision.confidence)
       - st.caption(f"Confidence: {decision.confidence:.0%}")
    4. Suggested actions:
       - st.subheader("Suggested Actions")
       - st.write(decision.suggested_actions) or render as bullets
    """
    ...


def render_context_panel(trace):
    """
    Render the intermediate TemporalContext as collapsible JSON.

    Steps to implement:
    1. with st.expander("View TemporalContext (deterministic state)"):
    2. st.json(trace["context"], expanded=True)
    3. st.caption(f"Signal count: {trace['signal_count']}")
    """
    ...


def render_trace_panel(trace):
    """
    Render the full reasoning trace — the killer feature.

    Steps to implement:
    1. with st.expander("View Full Reasoning Trace"):
    2. st.subheader("LLM Prompt")
    3. st.code(trace["prompt"], language="text")
    4. st.subheader("Raw LLM Response")
    5. st.code(trace["llm_response"], language="text")
    """
    ...


def main():
    """
    Main Streamlit app layout.

    Steps to implement:
    1. Page config:
       st.set_page_config(page_title="Stratum Demo",
                          page_icon="🌍", layout="wide")
    2. Header:
       st.title("🌍 Stratum")
       st.caption("Domain-agnostic temporal reasoning framework — "
                  "Signals → TemporalContext → ReasoningAgent → Decision")

    3. Sidebar (Panel 1):
       - st.sidebar.selectbox("Domain", ["sre", "markets"])
       - Scenarios dropdown based on domain (SRE_SCENARIOS or MARKET_SCENARIOS)
       - "Run Analysis" button (st.sidebar.button)

    4. When Run is clicked:
       - Generate signals via gen_sre/scenario or gen_market/scenario
       - Call the matching agent's reason_with_trace(signals)
       - Store results in st.session_state

    5. Main layout (Panels 2-4):
       - render_decision_panel(decision)
       - render_context_panel(trace)
       - render_trace_panel(trace)

    6. Error handling:
       - Wrap agent call in try/except
       - st.error(...) on failure (e.g. Ollama not running)
    """
    ...


if __name__ == "__main__":
    main()