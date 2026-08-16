"""
stratum/scripts/stress_test.py

Prolonged stress test for the Stratum SRE MVP.

Runs N iterations of the full pipeline (signal generation → TemporalContext
→ LLM → decision) over a configurable duration and prints a performance
summary: per-stage timings, success rates, confidence scores, and failures.

Usage:
    python3 scripts/stress_test.py --duration 300 --scenario cpu_spike --llm qwen2.5
    python3 scripts/stress_test.py --iterations 10 --scenario latency_degradation
"""

import argparse
import logging
import time
from datetime import datetime
from statistics import mean, median


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stratum-stress",
        description="Prolonged stress test for the Stratum SRE pipeline.",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Run for this many seconds (overrides --iterations).",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=10,
        help="Number of pipeline runs (default: 10).",
    )
    parser.add_argument(
        "--scenario",
        default="cpu_spike",
        choices=["cpu_spike", "memory_leak", "latency_degradation", "normal"],
        help="SRE scenario to run (default: cpu_spike).",
    )
    parser.add_argument(
        "--llm",
        default="qwen2.5",
        help="Ollama model name (default: qwen2.5).",
    )
    parser.add_argument(
        "--signal-window",
        type=int,
        default=30,
        help="Signal-generation window in seconds (default: 30).",
    )
    return parser


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    args = build_parser().parse_args()

    # Import here so a bad CLI invocation fails fast without importing the stack.
    from stratum.data.sre.scenarios import generate_scenario_signals
    from stratum.adapters.sre.output import SREAdapter
    from stratum.llm.ollama import OllamaLLM
    from stratum.core.reasoning_agent import ReasoningAgent

    adapter = SREAdapter()
    llm = OllamaLLM(model=args.llm, timeout=120)
    agent = ReasoningAgent(adapter=adapter, llm=llm)

    start_wall = time.time()
    iterations_done = 0
    timings: dict[str, list[float]] = {
        "signals": [],
        "state": [],
        "llm": [],
        "parse": [],
        "total": [],
    }
    successes = 0
    failures: list[dict] = []

    deadline = start_wall + args.duration if args.duration else None

    while True:
        # If a duration was set and we've passed it, stop.
        if deadline is not None and time.time() >= deadline:
            break
        if deadline is None and iterations_done >= args.iterations:
            break

        run_start = time.time()
        try:
            # ── 1. Signals ─────────────────────────────────────────
            t0 = time.time()
            signals = generate_scenario_signals(
                args.scenario, duration_seconds=args.signal_window
            )
            timings["signals"].append(time.time() - t0)

            # ── 2. State (deterministic, no LLM) ───────────────────
            t0 = time.time()
            context = adapter.build_state(signals)
            timings["state"].append(time.time() - t0)

            # ── 3. LLM (with retries) ──────────────────────────────
            prompt = adapter.build_prompt(context)
            t0 = time.time()
            llm_response = llm.generate(prompt)
            timings["llm"].append(time.time() - t0)

            # ── 4. Parse + assemble decision ────────────────────────
            if llm_response.startswith("ERROR:"):
                raise RuntimeError(llm_response)

            t0 = time.time()
            decision_data = adapter.parse_output(llm_response)
            timings["parse"].append(time.time() - t0)

            timings["total"].append(time.time() - run_start)
            iterations_done += 1
            successes += 1

            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] "
                f"iter={iterations_done} ok conf={decision_data.get('confidence', 0.0):.2f} "
                f"signals={len(signals)} context_events={context.event_count} "
                f"llm_time={timings['llm'][-1]:.1f}s "
                f"total={timings['total'][-1]:.1f}s"
            )
        except Exception as exc:  # noqa: BLE001 — stress test must keep going
            timings["total"].append(time.time() - run_start)
            iterations_done += 1
            failures.append(
                {
                    "iteration": iterations_done,
                    "error": str(exc)[:200],
                }
            )
            print(f"[{datetime.now().strftime('%H:%M:%S')}] iter={iterations_done} FAIL: {str(exc)[:150]}")

    elapsed = time.time() - start_wall

    # ── Summary ────────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print(f"STRESS TEST COMPLETE — {iterations_done} iterations in {elapsed:.1f}s")
    print(f"Scenario: {args.scenario} | LLM: {args.llm} | Window: {args.signal_window}s")
    print(f"Successes: {successes}/{iterations_done} ({100*successes/iterations_done:.1f}%)")
    if failures:
        print(f"Failures: {len(failures)}")
        for f in failures:
            print(f"  - iter {f['iteration']}: {f['error'][:120]}")
    print("─" * 60)
    for stage, vals in timings.items():
        if vals:
            print(
                f"{stage:<8s} mean={mean(vals):.2f}s  median={median(vals):.2f}s  "
                f"min={min(vals):.2f}s  max={max(vals):.2f}s  n={len(vals)}"
            )
    print("═" * 60)
    return 0 if successes == iterations_done else 1


if __name__ == "__main__":
    raise SystemExit(main())