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

DISCRIMINATING FEATURES (why the comparison is honest):
  --signal-count N   Generate N raw signals. Naive dumps ALL of them into
                     the prompt (token blowup / context overflow); the
                     TemporalContext path compresses to a fixed-size state.
  --messy            Inject noise: ~5% dropped rows + a misleading disk_usage
                     metric with random spikes that is NOT the root cause.
                     The naive LLM can chase the red herring; the state
                     builder ignores unknown metrics entirely.
  Strict scoring     Exact root-cause category match (root_cause field),
                     hallucination penalty (mentions metrics not present),
                     context-overflow detection.
  Token estimates    Prompt chars/4 ≈ tokens, reported per run so the
                     compression story is quantitative.
  Calibration        Mean confidence for correct vs incorrect responses —
                     a confidence score is only a win if it tracks accuracy.

Usage:
    python3 scripts/eval_benchmark.py --runs 3 --scenarios all
    python3 scripts/eval_benchmark.py --mode structured|naive|both
    python3 scripts/eval_benchmark.py --no-llm        # deterministic only
    python3 scripts/eval_benchmark.py --signal-count 500000 --runs 1 --scenarios cpu_spike
    python3 scripts/eval_benchmark.py --messy --runs 5 --scenarios all
"""

import argparse
import json
import logging
import statistics
import time
from datetime import datetime, timedelta
from typing import Optional

import numpy as np

# ── Ground-truth assertions for each scenario ────────────────────────────

# Which metric should surface as the ROOT CAUSE for each scenario.
# Used for exact root-cause classification (strict scoring).
SCENARIO_ROOT_CAUSE: dict[str, str] = {
    "cpu_spike": "cpu",
    "memory_leak": "memory",
    "latency_degradation": "latency",
    "normal": "",  # no incident — healthy
}

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

# Recognizable metric/service words for hallucination detection.
# If the LLM mentions a term in this list that is NOT among the metrics
# actually present in the input signals, that's a hallucination.
HALLUCINATION_VOCAB: list[str] = [
    "cpu", "memory", "mem", "latency", "disk", "network", "database",
    "queue", "connection pool", "container", "pod", "gpu", "io",
    "disk_usage", "error_rate", "request_rate",
]

# Rough token estimate heuristic (LLM tokens ≈ 4 chars for English/numeric).
TOKEN_CHARS_RATIO = 4.0

# Conservative context-length guard for local Ollama models (qwen2.5: 32K).
MAX_CONTEXT_TOKENS = 30000


# ── Token estimation ─────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Rough token estimate: length/4 (1 token ≈ 4 chars heuristic)."""
    return max(1, int(len(text) / TOKEN_CHARS_RATIO))


# ── Bulk signal generation (volume stress — no OTel overhead) ────────────

def generate_bulk_signals(
    incident_type: str,
    signal_count: int,
    service_name: str = "payment-api",
    seed: int = 42,
) -> list:
    """
    Fast synthetic signal generation at arbitrary volume.

    Used for --signal-count volume stress. Bypasses the OTel simulator
    entirely (no per-tick sleeps) so we can generate hundreds of thousands
    of signals in under a second. Produces the same metric names/units as
    the simulator but with incident semantics tuned per scenario.
    """
    from stratum.core.schemas import Signal

    rng = np.random.default_rng(seed)
    n_ticks = max(1, signal_count // 3)  # 3 metrics per tick
    ts0 = datetime(2026, 1, 1, 8, 0, 0)

    # ── Per-metric arrays ──────────────────────────────────────────
    cpu = np.full(n_ticks, 30.0) + rng.uniform(-3.0, 3.0, n_ticks)
    lat = rng.lognormal(np.log(0.08), 0.2, n_ticks)
    mem = np.full(n_ticks, 256.0 * 1024 * 1024)

    if incident_type == "cpu_spike":
        # Sustained saturation in the middle band of the window
        start, end = int(n_ticks * 0.25), int(n_ticks * 0.55)
        cpu[start:end] = rng.uniform(88.0, 99.1, end - start)
        lat[start:end] = rng.uniform(2.5, 6.2, end - start)  # causal latency
    elif incident_type == "memory_leak":
        # Linear growth across the window (grace period + leak)
        growth = np.linspace(0.0, 500.0 * 1024 * 1024, n_ticks)
        mem = mem + growth + rng.normal(0, 1_000_000, n_ticks)
    elif incident_type == "latency_degradation":
        mask = rng.random(n_ticks) < 0.30
        lat[mask] = rng.uniform(2.5, 6.2, int(mask.sum()))

    cpu = np.clip(cpu, 0.0, 100.0).round(2)
    lat = np.round(lat, 4)
    mem = mem.astype(int)

    # ── Assemble Signal objects ────────────────────────────────────
    signals: list = []
    for i in range(n_ticks):
        ts = ts0 + timedelta(seconds=i)
        tags = {"service": service_name, "environment": "production"}
        signals.append(Signal(timestamp=ts, name="cpu_usage", value=float(cpu[i]), unit="%", tags=tags))
        signals.append(Signal(timestamp=ts, name="memory_usage", value=float(mem[i]), unit="By", tags=tags))
        signals.append(Signal(timestamp=ts, name="latency_p99", value=float(lat[i]), unit="s", tags=tags))

    return signals


# ── Messy transforms — realistic noise + red herring ─────────────────────

def apply_messy(signals: list, seed: int) -> list:
    """
    Inject production messiness:
      1. Drop ~5% of signal rows (missing data).
      2. Add a misleading `disk_usage` metric with random spikes that is
         NOT the root cause. The state builder ignores unknown metrics;
         the naive LLM has to spot the red herring.
    """
    from stratum.core.schemas import Signal

    rng = np.random.default_rng(seed + 999)

    # 1. Drop ~5% of rows
    keep = rng.random(len(signals)) > 0.05
    signals = [s for s, k in zip(signals, keep) if k]

    # 2. Inject misleading disk_usage spikes on ~10% of ticks
    timestamps = sorted({s.timestamp for s in signals})
    disk_signals: list = []
    tags = {"service": signals[0].tags.get("service", "unknown"),
            "environment": "production", "misleading": "true"}
    for ts in timestamps:
        if rng.random() < 0.10:
            disk_signals.append(Signal(
                timestamp=ts,
                name="disk_usage",
                value=round(float(rng.uniform(60.0, 95.0)), 2),
                unit="%",
                tags=tags,
            ))

    return sorted(signals + disk_signals, key=lambda s: s.timestamp)


# ── Shared scoring — STRICT ──────────────────────────────────────────────

def score_response(
    analysis: str,
    root_cause: str,
    suggested_actions: list,
    reasoning_trace: str,
    expected_metric: list[str],
    scenario: str,
    present_metrics: set,
    run: int,
) -> dict:
    """
    Strictly score one LLM response against ground truth.

    Returns:
        valid_json      — response contained parseable JSON
        valid_fields    — JSON had all required schema fields
        correct_incident— expected metric keyword appears in analysis/actions
        strict_class    — expected root-cause category appears in root_cause
        hallucinated    — analysis mentions a metric keyword NOT present
        overflow        — prompt exceeded context guard (set by caller)
        detail          — human-readable failure reason
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

    analysis_lower = str(analysis).lower()
    root_cause_lower = str(root_cause).lower()

    # ── Incident-type match (loose keyword) ─────────────────────
    evidence_text = " ".join(
        [analysis_lower, *[str(a).lower() for a in suggested_actions]]
    )
    correct_incident = True
    for metric in expected_metric:
        keyword = METRIC_KEYWORDS.get(metric, metric)
        if keyword not in evidence_text:
            correct_incident = False
            break

    # For 'normal', the incident match means "no severe issues".
    if scenario == "normal":
        correct_incident = (
            "high" not in analysis_lower or "no" in analysis_lower
        )

    # ── Exact root-cause classification (STRICT) ────────────────
    expected_class = SCENARIO_ROOT_CAUSE[scenario]
    if expected_class:
        strict_class = expected_class in root_cause_lower
    else:
        # Normal: root cause should indicate healthy / no incident.
        strict_class = any(
            w in root_cause_lower
            for w in ["no", "normal", "healthy", "none", "unknown", "no issue"]
        )

    # ── Hallucination penalty (STRICT) ──────────────────────────
    hallucinated = False
    for term in HALLUCINATION_VOCAB:
        if term in evidence_text:
            # is this term actually a substring of any metric name that's present?
            term_is_grounded = any(term in metric_name for metric_name in present_metrics)
            if not term_is_grounded:
                hallucinated = True
                break

    detail = ""
    if not correct_incident or not strict_class or hallucinated:
        parts = []
        if not correct_incident:
            parts.append(f"expected metric '{expected_metric}'")
        if not strict_class:
            parts.append(
                f"expected root-cause class '{expected_class or 'healthy'}' "
                f"but root_cause='{root_cause_lower[:50]}'"
            )
        if hallucinated:
            parts.append("hallucinated metric not present in input")
        detail = (
            f"  run={run + 1}: {'; '.join(parts)} | "
            f"analysis: {analysis_lower[:100]}"
        )

    return {
        "valid_json": valid_json,
        "valid_fields": valid_fields,
        "correct_incident": correct_incident,
        "strict_class": strict_class,
        "hallucinated": hallucinated,
        "overflow": False,
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
        "Respond ONLY with valid JSON matching this schema:\n"
        '{"analysis": "...", "confidence": 0.0, '
        '"suggested_actions": ["..."], "root_cause": "..."}'
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
        help="Which LLM layer(s) to run (default: both).",
    )
    parser.add_argument(
        "--signal-count",
        type=int,
        default=0,
        help="Generate N raw signals instead of the scenario default. "
             "Naive prompt grows linearly with N and eventually overflows "
             "the context window; TemporalContext stays constant-size. "
             "(0 = use the scenario's configured duration)",
    )
    parser.add_argument(
        "--messy",
        action="store_true",
        help="Inject noise + a misleading disk_usage metric (red herring).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible signal generation.",
    )
    return parser


def _generate_signals(scenario: str, seed: int, signal_count: int, messy: bool) -> list:
    """
    Generate signals honoring --signal-count and --messy.

    Volume stress uses the fast numpy bulk generator; otherwise the OTel
    scenario generator is used.
    """
    if signal_count > 0:
        signals = generate_bulk_signals(
            incident_type=scenario, signal_count=signal_count, seed=seed
        )
    else:
        from stratum.data.sre.scenarios import generate_scenario_signals

        signals = generate_scenario_signals(scenario, seed=seed)

    if messy:
        signals = apply_messy(signals, seed=seed)

    return signals


def deterministic_eval(scenario: str, runs: int, seed: int) -> dict:
    """Benchmark the state builder without any LLM."""
    from stratum.adapters.sre.output import SREAdapter

    adapter = SREAdapter()
    checker = SCENARIO_EXPECTATIONS[scenario]
    results = {"pass": 0, "fail": 0, "event_counts": [], "details": []}

    for run in range(runs):
        signals = _generate_signals(scenario, seed + run, 0, False)
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
    signal_count: int = 0,
    messy: bool = False,
) -> dict:
    """
    Run the LLM layer for one scenario in either mode.

    mode="structured": signals → build_state → TemporalContext → build_prompt → LLM
    mode="naive":      signals → build_naive_prompt (raw)        → LLM

    The ONLY difference between modes is how the prompt is constructed.
    The LLM call, response parsing, and ground-truth scoring are identical,
    so the structured and naive results are directly comparable.
    """
    from stratum.adapters.sre.output import SREAdapter
    from stratum.llm.ollama import OllamaLLM

    adapter = SREAdapter()
    llm = OllamaLLM(model=llm_model, timeout=120)

    results = {
        "valid_json": 0,
        "valid_fields": 0,
        "correct_incident": 0,
        "strict_class": 0,
        "hallucinated": 0,
        "overflow": 0,
        "confidence_scores": [],
        "confidence_correct": [],
        "confidence_wrong": [],
        "llm_times": [],
        "prompt_chars": [],
        "prompt_tokens": [],
        "details": [],
    }
    expected_metric = SCENARIO_METRIC_EXPECTATIONS[scenario]

    for run in range(runs):
        signals = _generate_signals(scenario, seed + run, signal_count, messy)
        present_metrics = {s.name for s in signals}

        # ── The only branch: how the prompt is built ──────────────
        if mode == "naive":
            prompt = build_naive_prompt(signals)
        else:
            context = adapter.build_state(signals)
            prompt = adapter.build_prompt(context)

        results["prompt_chars"].append(len(prompt))
        tok_est = estimate_tokens(prompt)
        results["prompt_tokens"].append(tok_est)

        # ── Context-overflow guard (naive volume stress) ──────────
        if tok_est > MAX_CONTEXT_TOKENS and mode == "naive":
            results["overflow"] += 1
            results["llm_times"].append(0.0)
            results["confidence_scores"].append(0.0)
            results["confidence_wrong"].append(0.0)
            results["details"].append(
                f"  run={run + 1}: CONTEXT OVERFLOW — "
                f"prompt ≈{tok_est:,} tokens exceeds {MAX_CONTEXT_TOKENS:,}-token guard "
                f"({len(signals):,} raw signals dumped into naive prompt)"
            )
            continue

        # ── Same LLM call either way ─────────────────────────────
        t0 = time.time()
        raw = llm.generate(prompt)
        llm_time = time.time() - t0
        results["llm_times"].append(llm_time)

        # ── Same parsing either way ──────────────────────────────
        decision_data = adapter.parse_output(raw)
        confidence = max(0.0, min(1.0, float(decision_data.get("confidence", 0.0))))

        # ── Same STRICT grading either way ────────────────────────
        reasoning_trace = json.dumps(decision_data, default=str)
        score = score_response(
            analysis=str(decision_data.get("analysis", "")),
            root_cause=str(decision_data.get("root_cause", "")),
            suggested_actions=list(decision_data.get("suggested_actions", [])),
            reasoning_trace=reasoning_trace,
            expected_metric=expected_metric,
            scenario=scenario,
            present_metrics=present_metrics,
            run=run,
        )

        results["valid_json"] += int(score["valid_json"])
        results["valid_fields"] += int(score["valid_fields"])
        results["correct_incident"] += int(score["correct_incident"])
        results["strict_class"] += int(score["strict_class"])
        results["hallucinated"] += int(score["hallucinated"])
        results["confidence_scores"].append(confidence)
        if score["strict_class"] and score["correct_incident"]:
            results["confidence_correct"].append(confidence)
        else:
            results["confidence_wrong"].append(confidence)
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
    print(f"  strict root-cause:{res['strict_class']}/{runs} ({100.0 * res['strict_class'] / n:.0f}%)")
    print(f"  hallucinated:    {res['hallucinated']}/{runs}")
    if res["overflow"]:
        print(f"  context overflow:{res['overflow']}/{runs}")
    if res["confidence_scores"]:
        print(f"  confidence:      mean={statistics.mean(res['confidence_scores']):.2f}")
    if res["llm_times"]:
        print(f"  llm time:        mean={statistics.mean(res['llm_times']):.1f}s, max={max(res['llm_times']):.1f}s")
    if res["prompt_tokens"]:
        print(
            f"  prompt tokens:   mean={statistics.mean(res['prompt_tokens']):,.0f} "
            f"(chars mean={statistics.mean(res['prompt_chars']):,.0f})"
        )
    if res["confidence_correct"] and res["confidence_wrong"]:
        cc = statistics.mean(res["confidence_correct"])
        cw = statistics.mean(res["confidence_wrong"])
        print(f"  calibration:     conf-correct={cc:.2f} vs conf-wrong={cw:.2f} "
              f"(Δ={cc - cw:+.2f}{' — informative' if cc > cw else ' — NOT informative'})")
    for detail in res["details"]:
        print(detail)


def _print_comparison(scores: dict) -> None:
    """Final cross-scenario structured-vs-naive summary table."""
    print("\n" + "═" * 70)
    print("COMPARISON SUMMARY — Structured (TemporalContext) vs Naive (raw)")
    print("═" * 70)
    header = f"{'Scenario':<20} {'Layer':<12} {'Class%':>7} {'Halluc':>7} {'Tok':>9}"
    print(header)
    print("-" * len(header))
    for sc, layers in scores.items():
        if "structured" in layers:
            s = layers["structured"]
            n = max(1, s["runs"])
            print(
                f"{sc:<20} {'structured':<12} "
                f"{100.0 * s['strict_class'] / n:>6.0f}% "
                f"{s['hallucinated']:>7} "
                f"{statistics.mean(s['prompt_tokens']):>8,.0f}"
            )
        if "naive" in layers:
            s = layers["naive"]
            n = max(1, s["runs"])
            print(
                f"{sc:<20} {'naive':<12} "
                f"{100.0 * s['strict_class'] / n:>6.0f}% "
                f"{s['hallucinated']:>7} "
                f"{statistics.mean(s['prompt_tokens']):>8,.0f}"
            )
    print("═" * 70)


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    args = build_parser().parse_args()

    scenarios = (
        list(SCENARIO_EXPECTATIONS.keys())
        if args.scenarios == "all"
        else [s.strip() for s in args.scenarios.split(",")]
    )

    comparison: dict = {}

    for scenario in scenarios:
        if scenario not in SCENARIO_EXPECTATIONS:
            print(f"Skipping unknown scenario: {scenario}")
            continue

        print("\n" + "═" * 70)
        print(f"SCENARIO: {scenario}" + ("  [MESSY]" if args.messy else ""))
        if args.signal_count:
            print(f"VOLUME: {args.signal_count:,} raw signals")
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

        comparison[scenario] = {}

        # ── Layer 2: structured LLM (optional) ─────────────────────
        if not args.no_llm and mode in ("structured", "both"):
            llm_res = run_eval(
                scenario,
                mode="structured",
                runs=args.runs,
                seed=args.seed,
                llm_model=args.llm,
                signal_count=args.signal_count,
                messy=args.messy,
            )
            llm_res["runs"] = args.runs
            comparison[scenario]["structured"] = llm_res
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
                signal_count=args.signal_count,
                messy=args.messy,
            )
            naive_res["runs"] = args.runs
            comparison[scenario]["naive"] = naive_res
            _print_llm_layer(
                f"LLM Reasoning Layer (naive, no TemporalContext) — "
                f"model={args.llm}",
                naive_res,
                args.runs,
            )

    if not args.no_llm and comparison:
        _print_comparison(comparison)

    print("\n" + "═" * 70)
    print("BENCHMARK COMPLETE")
    print("═" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())