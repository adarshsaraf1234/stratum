"""
stratum/scripts/eval_benchmark.py

Evaluation benchmark for the Stratum SRE pipeline.

Three layers of evaluation:
  1. Deterministic layer (no LLM) — does the TemporalContext correctly
     capture ground-truth events for each known scenario?
  2. LLM reasoning layer (structured) — does the model return valid
     structured output that correctly identifies the incident type,
     given the deterministic TemporalContext?
  3. LLM reasoning layer (naive) — SAME question, but raw signals are
     dumped straight into the prompt with NO TemporalContext processing.
     This is the baseline the whole framework exists to beat:

         naive:    LLM(raw signals) → answer
         stratum:  signals → TemporalContext → LLM → decision

    The structured and naive LLM layers share a single run_eval() —
    the ONLY difference is how the prompt is constructed. The LLM call,
    response parsing, and ground-truth scoring are identical, so the
    two modes are directly comparable.

Ground truth comes from the scenario name:
    cpu_spike            → expect CPU events detected
    memory_leak          → expect memory events detected
    latency_degradation  → expect latency events detected
    normal               → expect no high-severity events

Usage:
    python3 scripts/eval_benchmark.py --runs 3 --scenarios all
    python3 scripts/eval_benchmark.py --runs 5 --scenarios cpu_spike,memory_leak
    python3 scripts/eval_benchmark.py --no-llm   # deterministic-only eval
    python3 scripts/eval_benchmark.py --naive    # also run naive baseline
    python3 scripts/eval_benchmark.py --mode structured|naive|both  # explicit layer(s)
"""

import argparse
import json
import logging
import statistics
import time

# ── Ground-truth assertions for each scenario ────────────────────────────

# Which metrics should surface in a correct analysis for each scenario.
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

# Metric → loose keyword the LLM should mention in a correct analysis.
METRIC_KEYWORDS: dict[str, str] = {
    "cpu_usage": "cpu",
    "memory_usage": "mem",
    "latency_p99": "latency",
}


# ── Shared scoring ───────────────────────────────────────────────────────

def score_response(
    analysis: str,
    suggested_actions: list,
    reasoning_trace: str,
    expected_metric: list[str],
    scenario: str,
    run: int,
) -> dict:
    """
    Score one LLM response against ground truth.

    Used by BOTH the structured and naive paths so results are directly
    comparable. Returns {valid_json, valid_fields, correct_incident, detail}.
    """
    # ── Structured output validity ─────────────────────────────
    valid_json = False
    valid_fields = False
    try:
        parsed = json.loads(reasoning_trace)
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

    # ── Incident-type match ────────────────────────────────────
    evidence_text = " ".join(
        [str(analysis), *[str(a) for a in suggested_actions]]
    ).lower()
    correct = True
    for metric in expected_metric:
        keyword = METRIC_KEYWORDS.get(metric, metric)
        if keyword not in evidence_text:
            correct = False
            break

    # For 'normal', the correct answer is that there are no severe issues.
    if scenario == "normal":
        correct = (
            "high" not in str(analysis).lower()
            or "no" in str(analysis).lower()
        )

    detail = ""
    if not correct:
        detail = (
            f"  run={run + 1}: expected metric '{expected_metric}', "
            f"LLM said: {str(analysis)[:100]}"
        )

    return {
        "valid_json": valid_json,
        "valid_fields": valid_fields,
        "correct_incident": correct,
        "detail": detail,
    }


# ── Naive prompt builder — NO deterministic processing ───────────────────

def build_naive_prompt(signals: list) -> str:
    """
    Build a raw-signal prompt with NO TemporalContext, NO state builder.

    This is the "naive" baseline: dump raw metric rows into the prompt and
    ask the LLM to identify the root cause directly. No event detection,
    trend analysis, or aggregation is performed — just raw telemetry.
    """
    lines = [f"{s.timestamp} {s.name}={s.value}{s.unit}" for s in signals]
    return (
        "Here is raw infrastructure telemetry data:\n"
        + "\n".join(lines)
        + "\n\nWhat is the root cause of any issue, if there is one? "
        "Respond with the same JSON schema as before."
    )


# ── Eval layers ──────────────────────────────────────────────────────────

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
        "--naive",
        action="store_true",
        help="Legacy alias for --mode both — run structured AND naive layers.",
    )
    parser.add_argument(
        "--mode",
        choices=["structured", "naive", "both"],
        default="both",
        help="Which LLM layer(s) to run (default: both). To run them in "
             "parallel processes: terminal 1 → --mode structured, "
             "terminal 2 → --mode naive.",
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


def run_eval(
    scenario: str,
    mode: str = "structured",
    runs: int = 3,
    seed: int = 42,
    llm_model: str = "qwen2.5",
) -> dict:
    """
    Run the LLM layer for one scenario in either mode.

    mode="structured": signals → build_state → TemporalContext → build_prompt → LLM
    mode="naive":      signals → build_naive_prompt (raw)        → LLM

    The ONLY difference between modes is how the prompt is constructed.
    The LLM call, response parsing, and ground-truth scoring are identical,
    so the structured and naive results are directly comparable.
    """
    from stratum.data.sre.scenarios import generate_scenario_signals
    from stratum.adapters.sre.output import SREAdapter
    from stratum.llm.ollama import OllamaLLM

    adapter = SREAdapter()
    llm = OllamaLLM(model=llm_model, timeout=120)

    results = {
        "valid_json": 0,
        "valid_fields": 0,
        "correct_incident": 0,
        "confidence_scores": [],
        "llm_times": [],
        "details": [],
    }
    expected_metric = SCENARIO_METRIC_EXPECTATIONS[scenario]

    for run in range(runs):
        signals = generate_scenario_signals(scenario, seed=seed + run)

        # ── The only branch: how the prompt is built ──────────────
        if mode == "naive":
            prompt = build_naive_prompt(signals)
        else:
            context = adapter.build_state(signals)
            prompt = adapter.build_prompt(context)

        # ── Same LLM call either way ─────────────────────────────
        t0 = time.time()
        raw = llm.generate(prompt)
        llm_time = time.time() - t0
        results["llm_times"].append(llm_time)

        # ── Same parsing either way ──────────────────────────────
        decision_data = adapter.parse_output(raw)

        # ── Same grading either way ──────────────────────────────
        reasoning_trace = json.dumps(decision_data, default=str)
        score = score_response(
            analysis=str(decision_data.get("analysis", "")),
            suggested_actions=list(decision_data.get("suggested_actions", [])),
            reasoning_trace=reasoning_trace,
            expected_metric=expected_metric,
            scenario=scenario,
            run=run,
        )

        results["valid_json"] += int(score["valid_json"])
        results["valid_fields"] += int(score["valid_fields"])
        results["correct_incident"] += int(score["correct_incident"])
        results["confidence_scores"].append(
            max(0.0, min(1.0, float(decision_data.get("confidence", 0.0))))
        )
        if score["detail"]:
            results["details"].append(score["detail"])

    return results


def _print_llm_layer(title: str, res: dict, runs: int) -> None:
    """Print one LLM-layer result block (structured or naive)."""
    n = max(1, runs)
    print(f"\n[{title}]")
    print(f"  valid JSON:      {res['valid_json']}/{runs} ({100.0 * res['valid_json'] / n:.0f}%)")
    print(f"  valid fields:    {res['valid_fields']}/{runs} ({100.0 * res['valid_fields'] / n:.0f}%)")
    print(f"  incident match:  {res['correct_incident']}/{runs} ({100.0 * res['correct_incident'] / n:.0f}%)")
    if res["confidence_scores"]:
        print(f"  confidence:      mean={statistics.mean(res['confidence_scores']):.2f}")
    if res["llm_times"]:
        print(f"  llm time:        mean={statistics.mean(res['llm_times']):.1f}s, max={max(res['llm_times']):.1f}s")
    for detail in res["details"]:
        print(detail)


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

        # Resolve which LLM layers to run. --naive is a legacy alias
        # for --mode both.
        mode = args.mode
        if args.naive:
            mode = "both"

        # ── Layer 2: structured LLM (optional) ─────────────────────
        if not args.no_llm and mode in ("structured", "both"):
            llm_res = run_eval(
                scenario,
                mode="structured",
                runs=args.runs,
                seed=args.seed,
                llm_model=args.llm,
            )
            _print_llm_layer(
                f"LLM Reasoning Layer (structured) — model={args.llm}",
                llm_res,
                args.runs,
            )

        # ── Layer 3: naive baseline (optional) ─────────────────────
        if not args.no_llm and mode in ("naive", "both"):
            naive_res = run_eval(
                scenario,
                mode="naive",
                runs=args.runs,
                seed=args.seed,
                llm_model=args.llm,
            )
            _print_llm_layer(
                f"LLM Reasoning Layer (naive, no TemporalContext) — "
                f"model={args.llm}",
                naive_res,
                args.runs,
            )

    print("\n" + "═" * 70)
    print("BENCHMARK COMPLETE")
    print("═" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())