"""
stratum/main.py

CLI entry point for Stratum — run scenarios, list them, or serve the API.
"""

import argparse
import logging
import sys
from typing import Optional

from stratum.llm.ollama import OllamaLLM
from stratum.adapters.sre.output import SREAdapter
from stratum.adapters.markets.output import MarketAdapter
from stratum.core.reasoning_agent import ReasoningAgent
from stratum.data.sre.scenarios import SRE_SCENARIOS
from stratum.data.markets.scenarios import MARKET_SCENARIOS

logger = logging.getLogger(__name__)


def build_agent(domain: str, llm_model: str = "llama3") -> ReasoningAgent:
    """
    Factory for constructing a ReasoningAgent for a given domain.

    Steps to implement:
    1. Create OllamaLLM(model=llm_model)
    2. Based on domain:
       - "sre"     → SREAdapter()
       - "markets" → MarketAdapter()
       - else raise ValueError
    3. Return ReasoningAgent(adapter=adapter, llm=llm)
    """
    ...


def run_scenario(domain: str, scenario: str, llm_model: str) -> None:
    """
    Run a single demo scenario and print the structured decision to stdout.

    Steps to implement:
    1. Agent = build_agent(domain, llm_model)
    2. Generate signals:
       - sre:     generate_scenario_signals(scenario) from data.sre.scenarios
       - markets: generate_scenario_signals(scenario) from data.markets.scenarios
    3. decision, trace = agent.reason_with_trace(signals)
    4. Print (formatted):
       ═════════════════════════════
       Domain: {decision.domain}
       Confidence: {decision.confidence:.0%}
       ═════════════════════════════
       {decision.analysis}
       Suggested actions:
         - action 1
         - action 2
       ═════════════════════════════
       (TemporalContext summary: {trace['context']['summary']})

    5. If decision.analysis starts with "ERROR:", exit with code 1
       (e.g. Ollama not running)
    """
    ...


def list_scenarios() -> None:
    """
    Print all available scenarios for both domains.

    Steps to implement:
    1. For each SRE scenario: print "sre/{name} - {description}"
    2. For each market scenario: print "markets/{name} - {description}"
    """
    ...


def main(argv: Optional[list[str]] = None) -> int:
    """
    CLI argument parser and dispatch.

    Subcommands:
        run <domain> --scenario <name> [--llm MODEL]
            Run a scenario through the reasoning pipeline
        list-scenarios
            List available demo scenarios
        serve [--port PORT] [--llm MODEL]
            Start the FastAPI server (delegates to uvicorn)

    Steps to implement:
    1. argparse.ArgumentParser(prog="stratum", description=...)
    2. Subparsers with parent parser for --llm
    3. Dispatch to run_scenario / list_scenarios / serve
    4. Return 0 on success, non-zero on failure
    """
    ...


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())