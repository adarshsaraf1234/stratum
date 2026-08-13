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
from stratum.data.sre.scenarios import (
    SRE_SCENARIOS,
    generate_scenario_signals as generate_sre_scenario_signals,
)
from stratum.data.markets.scenarios import (
    MARKET_SCENARIOS,
    generate_scenario_signals as generate_market_scenario_signals,
)

logger = logging.getLogger(__name__)

# qwen2.5 default — 32K context (vs llama3's 8K) gives headroom for the
# TemporalContext JSON embedded in the prompt.
DEFAULT_LLM_MODEL = "qwen2.5"

# ── UI constants ──────────────────────────────────────────────────────────
SEPARATOR = "═" * 33


def build_agent(domain: str, llm_model: str = DEFAULT_LLM_MODEL) -> ReasoningAgent:
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
    llm = OllamaLLM(model=llm_model)

    if domain == "sre":
        adapter = SREAdapter()
    elif domain == "markets":
        adapter = MarketAdapter()
    else:
        raise ValueError(
            f"Unknown domain '{domain}'. Expected 'sre' or 'markets'."
        )

    return ReasoningAgent(adapter=adapter, llm=llm)


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
    # ── 1. Agent ────────────────────────────────────────────────────
    agent = build_agent(domain, llm_model)

    # ── 2. Signals for the named scenario ───────────────────────────
    if domain == "sre":
        signals = generate_sre_scenario_signals(scenario)
    else:
        signals = generate_market_scenario_signals(scenario)

    # ── 3. Full pipeline with trace ─────────────────────────────────
    decision, trace = agent.reason_with_trace(signals)

    # ── 4. Format output ────────────────────────────────────────────
    print()
    print(SEPARATOR)
    print(f"Domain: {decision.domain}")
    print(f"Confidence: {decision.confidence:.0%}")
    print(SEPARATOR)
    print(decision.analysis)
    print("Suggested actions:")
    if decision.suggested_actions:
        for action in decision.suggested_actions:
            print(f"  - {action}")
    else:
        print("  (none)")
    print(SEPARATOR)
    print(f"(TemporalContext summary: {trace['context'].get('summary', 'N/A')})")
    print()

    # ── 5. Exit non-zero on pipeline errors (e.g. Ollama down) ──────
    if decision.analysis.startswith("ERROR:"):
        sys.exit(1)


def list_scenarios() -> None:
    """
    Print all available scenarios for both domains.

    Steps to implement:
    1. For each SRE scenario: print "sre/{name} - {description}"
    2. For each market scenario: print "markets/{name} - {description}"
    """
    print("Available SRE scenarios:")
    for name, config in SRE_SCENARIOS.items():
        print(f"  sre/{name} - {config.get('description', 'No description')}")

    print()
    print("Available markets scenarios:")
    for name, config in MARKET_SCENARIOS.items():
        print(f"  markets/{name} - {config.get('description', 'No description')}")


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
    parser = argparse.ArgumentParser(
        prog="stratum",
        description=(
            "Domain-agnostic temporal reasoning framework — "
            "signals → TemporalContext → ReasoningAgent → decision."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── run <domain> --scenario <name> [--llm MODEL] ─────────────────
    run_parser = subparsers.add_parser(
        "run", help="Run a scenario through the reasoning pipeline"
    )
    run_parser.add_argument(
        "domain", choices=["sre", "markets"], help="Domain adapter to use"
    )
    run_parser.add_argument(
        "--scenario", required=True, help="Scenario name (see list-scenarios)"
    )
    run_parser.add_argument(
        "--llm", default=DEFAULT_LLM_MODEL, help="Ollama model name"
    )

    # ── list-scenarios ──────────────────────────────────────────────
    subparsers.add_parser(
        "list-scenarios", help="List available demo scenarios"
    )

    # ── serve [--port PORT] [--llm MODEL] ───────────────────────────
    serve_parser = subparsers.add_parser(
        "serve", help="Start the FastAPI server (delegates to uvicorn)"
    )
    serve_parser.add_argument("--port", type=int, default=8000)
    serve_parser.add_argument("--llm", default=DEFAULT_LLM_MODEL)

    args = parser.parse_args(argv)

    try:
        if args.command == "run":
            run_scenario(args.domain, args.scenario, args.llm)
        elif args.command == "list-scenarios":
            list_scenarios()
        elif args.command == "serve":
            _serve(args.port, args.llm)
        else:
            parser.print_help()
            return 1
    except KeyError as e:
        # Unknown scenario name — get_scenario() raises with a helpful
        # message listing the available options.
        logger.error("%s", e)
        return 1
    except ValueError as e:
        logger.error("%s", e)
        return 1
    except Exception as e:  # noqa: BLE001 — CLI should never traceback
        logger.error("Unexpected error: %s", e)
        return 1

    return 0


def _serve(port: int, llm_model: str) -> None:
    """
    Start the FastAPI server via uvicorn.

    Delegates to stratum.api.main.create_app(). If the API layer is not
    yet implemented, fails with a clear error instead of a traceback.
    """
    try:
        import uvicorn

        from stratum.api.main import create_app

        app = create_app(llm_model=llm_model)
        if app is None:
            raise RuntimeError(
                "create_app() returned None — the API layer is not "
                "implemented yet."
            )
        uvicorn.run(app, host="0.0.0.0", port=port)
    except ImportError as e:
        raise RuntimeError(
            "Cannot start API server — missing dependency. "
            "Run: pip install fastapi uvicorn"
        ) from e


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())