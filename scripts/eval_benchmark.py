"""
stratum/scripts/eval_benchmark.py

Evaluation benchmark for the Stratum SRE pipeline.

Two-layer evaluation:
  1. Deterministic layer (no LLM) — does the TemporalContext correctly
     capture ground-truth events for each known scenario?
  2. LLM reasoning layer — does the model return valid structured output
     that correctly identifies the incident type?

Ground truth comes from the scenario name:
    cpu_spike            → expect CPU/SRE events detected
    memory_leak          → expect memory events detected
    latency_degradation  → expect latency events detected
    normal               → expect no high-severity events

Usage:
    python3 scripts/eval_benchmark.py --runs 3 --scenarios all
    python3 scripts/eval_benchmark.py --runs 5 --scenarios cpu_spike,memory_leak
    python3 scripts/eval_benchmark.py --no-llm   # deterministic-only eval
"""

import argparse
import logging
import os
import statistics
import time
from datetime import datetime

# ── Ground-truth assertions for each scenario ────────────────────────────

# Which metrics should have events in a correct TemporalContext.
SCENARIO_METRIC_EXPECTATIONS: dict[str, list[str]] = {
    "cpu_spike": ["cpu_usage"],
    "memory_leak": ["memory_usage"],
    "latency_degradation": ["latency_p99"],
    "normal": [],  # no metric should have events
}

# Expected state outcome for the deterministic layer.
SCENARIO_EXPECTATIONS: dict[str, callable] = {
    # A normal scenario should have zero events.
    "normal": lambda ctx: len(ctx.events) == 0,
    # An incident scenario should have at least one event in the right metric.
    "cpu_spike": lambda ctx: any(
        e.source == "cpu_usage" for e in ctx.events
    ),
    "memory_leak": lambda ctx: any(
        e.source == "memory_usage" for e in ctx.events
    ),
    "latency_degradation": lambda ctx: any(
        e.source == "latency_p99" for e in ctx.events
    ),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stratum-eval",
        description="Evaluation benchmark for the Stratum SRE pipeline.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Number of runs per scenario (default: 3).",
    )
    parser.add_argument(
        "--scenarios",
        default="all",
        help="Comma-separated scenarios, or 'all' (default: all).",
    )
    parser.add_argument(
        "--llm",
        default="qwen2.5",
        help="Ollama model for the LLM layer (default: qwen2.5).",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip the LLM layer — deterministic state-builder eval only.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible signal generation.",
    )
    return parser


def deterministic_eval(scenario: str, runs: int, seed: int) -> dict:
    """Benchmark the state builder without any LLM."""
    from stratum.data.sre.scenarios import generate_scenario_signals
    from stratum.adapters.sre.output import SREAdapter

    adapter = SREAdapter()
    checker = SCENARIO_EXPECTATIONS[scenario]
    results = {"pass": 0, "fail": 0, "event_counts": [], "details": []}

    for run in range(runs):
        signals = generate_scenario_signals(scenario, seed=seed + run)
        context = adapter.build_state(signals)
        ok = checker(context)

        results["event_counts"].append(context.event_count)
        if ok:
            results["pass"] += 1
        else:
            results["fail"] += 1
            events_desc = ", ".join(
                f"{e.source}({e.severity})" for e in context.events
            )
            results["details"].append(
                f"  run={run + 1}: expected {SCENARIO_METRIC_EXPECTATIONS[scenario]}, "
                f"got events=[{events_desc}]"
            )

    return results


def llm_eval(scenario: str, runs: int, seed: int, llm_model: str) -> dict:
    """Benchmark the full pipeline including LLM reasoning."""
    from stratum.data.sre.scenarios import generate_scenario_signals
    from stratum.adapters.sre.output import SREAdapter
    from stratum.core.reasoning_agent import ReasoningAgent
    from stratum.llm.ollama import OllamaLLM

    adapter = SREAdapter()
    llm = OllamaLLM(model=llm_model, timeout=120)
    agent = ReasoningAgent(adapter=adapter, llm=llm)

    results = {
        "valid_json": 0,
        "valid_fields": 0,
        "correct_incident": 0,
        "confidence_scores": [],
        "llm_times": [],
        "details": [],
    }

    # Map determined by which metric shows events in the context.
    # We compare the LLM's cited root_cause / evidence against ground truth.
    expected_metric = SCENARIO_METRIC_EXPECTATIONS[scenario]

    for run in range(runs):
        signals = generate_scenario_signals(scenario, seed=seed + run)

        t0 = time.time()
        decision, trace = agent.reason_with_trace(signals)
        llm_time = time.time() - t0
        results["llm_times"].append(llm_time)

        # ── Structured output validity ─────────────────────────────
        import json

        valid_json = False
        valid_fields = False
        try:
            parsed = json.loads(decision.reasoning_trace)
            valid_json = True
            required = [
                "analysis",
                "confidence",
                "suggested_actions",
                "root_cause",
            ]
            valid_fields = all(k in parsed for k in required)
        except (json.JSONDecodeError, TypeError):
            pass

        if valid_json:
            results["valid_json"] += 1
        if valid_fields:
            results["valid_fields"] += 1

        # ── Incident-type match ────────────────────────────────────
        # Check if the LLM's evidence/analysis mentions the expected metric.
        evidence_text = " ".join(
            [
                str(decision.analysis),
                *getattr(decision, "suggested_actions", []),
            ]
        ).lower()
        correct = True
        for metric in expected_metric:
            # Metric names map loosely: cpu_usage→cpu, memory_usage→memory, latency_p99→latency
            keyword = {
                "cpu_usage": "cpu",
                "memory_usage": "mem",
                "latency_p99": "latency",
            }.get(metric, metric)
            if keyword not in evidence_text:
                correct = False
                break

        # For 'normal', the correct answer is there are no severe issues.
        if scenario == "normal":
            correct = "high" not in str(decision.analysis).lower() or "no" in str(decision.analysis).lower()

        if correct:
            results["correct_incident"] += 1
        else:
            results["details"].append(
                f"  run={run + 1}: expected metric '{expected_metric}', "
                f"LLM said: {str(decision.analysis)[:100]}"
            )

        results["confidence_scores"].append(decision.confidence)

    return results


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    args = build_parser().parse_args()

    scenarios = (
        list(SCENARIO_EXPECTATIONS.keys())
        if args.scenarios == "all"
        else [s.strip() for s in args.scenarios.split(",")]
    )

    for scenario in scenarios:
        if scenario not in SCENARIO_EXPECTATIONS:
            print(f"Skipping unknown scenario: {scenario}")
            continue

        print("\n" + "═" * 70)
        print(f"SCENARIO: {scenario}")
        print("═" * 70)

        # ── Layer 1: deterministic ─────────────────────────────────
        det = deterministic_eval(scenario, args.runs, args.seed)
        det_rate = 100.0 * det["pass"] / max(1, det["pass"] + det["fail"])
        print(f"\n[Deterministic State Builder] pass={det['pass']}/{det['pass'] + det['fail']} ({det_rate:.0f}%)")
        if det["event_counts"]:
            print(f"  event counts: {det['event_counts']}")
        for detail in det["details"]:
            print(detail)

        # ── Layer 2: LLM (optional) ────────────────────────────────
        if not args.no_llm:
            llm_res = llm_eval(scenario, args.runs, args.seed, args.llm)
            n = max(1, args.runs)
            print(f"\n[LLM Reasoning Layer] model={args.llm}")
            print(f"  valid JSON:      {llm_res['valid_json']}/{args.runs} ({100.0 * llm_res['valid_json'] / n:.0f}%)")
            print(f"  valid fields:    {llm_res['valid_fields']}/{args.runs} ({100.0 * llm_res['valid_fields'] / n:.0f}%)")
            # Only meaningful for incident scenarios, skip match for normal.
            print(f"  incident match:  {llm_res['correct_incident']}/{args.runs} ({100.0 * llm_res['correct_incident'] / n:.0f}%)")
            if llm_res["confidence_scores"]:
                print(f"  confidence:      mean={statistics.mean(llm_res['confidence_scores']):.2f}")
            if llm_res["llm_times"]:
                print(f"  llm time:        mean={statistics.mean(llm_res['llm_times']):.1f}s, max={max(llm_res['llm_times']):.1f}s")
            for detail in llm_res["details"]:
                print(detail)

    print("\n" + "═" * 70)
    print("BENCHMARK COMPLETE")
    print("═" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())