# Stratum

A **domain-agnostic temporal reasoning framework** for understanding why complex systems behave the way they do.

```
Raw time-series signals → TemporalContext (deterministic) → LLM reasoning → StructuredDecision
```

Stratum never feeds raw telemetry to an LLM. Instead, it first compresses arbitrary-volume, noisy time-series data into a small, verified, structured state — **TemporalContext** (events, trends, segments, periodicity, plain-English summary) — and only *then* asks the LLM to reason. The result is a structured, auditable decision with a confidence score and a full reasoning trace.

---

## Why TemporalContext?

The naive approach is `LLM(raw data) → answer`. It fails in production for three reasons:

| Problem | Naive (raw signals) | Stratum (TemporalContext) |
|---------|---------------------|---------------------------|
| **Scale** | Prompt grows linearly — at 100K signals the prompt is ~1M tokens (overflows a 32K context window) | Constant-size state — the prompt stays at ~5K tokens regardless of input volume |
| **Messiness** | The LLM chases misleading metrics and invents causes ("disk usage", "network traffic") | Only verified, deterministic events are surfaced; unknown metrics are ignored |
| **Trust** | The LLM reasons over impressions; confidence is often higher when it's *wrong* | The LLM reasons over provable, reproducible facts; you can always print and audit the state |

---

## Benchmark results (qwen2.5, local)

### 1. Root-cause accuracy — strict classification

Across 4 SRE scenarios × 5 runs each:

| Scenario | Structured (TemporalContext) | Naive (raw signals) |
|----------|:---:|:---:|
| normal | **100%** | 40% |
| cpu_spike | **100%** | 60% |
| memory_leak | **80%** | **20%** |
| latency_degradation | **80%** | 80% |
| **Average** | **90%** | **50%** |

The naive LLM cannot identify root cause from raw rows — it defaults to "no clear indication" or "variable CPU/memory usage". The structured path reasons over verified events ("memory usage rising at +38%/min").

### 2. Robustness — messy production data

With injected noise (5% dropped rows) and a misleading `disk_usage` red-herring metric:

| Scenario | Structured | Naive |
|----------|:---:|:---:|
| memory_leak | **100%** | 20% |
| latency_degradation | **80%** | 60% |

The naive LLM blames *"high disk usage"* for a memory leak. The structured path ignores the unknown `disk_usage` metric entirely.

### 3. Scale — token compression

| Raw signals | Structured prompt | Naive prompt | Ratio |
|------------:|------------------:|-------------:|------:|
| 720 | 748 tokens | 7,462 tokens | 10× |
| 10,000 | 1,001 tokens | 103,180 tokens | 103× |
| 100,000 | 4,908 tokens | **1,031,590 tokens** | **210×** |

At 100K signals the naive approach is *impossible* — the prompt exceeds any local model's context window. Stratum runs identically at any volume.

### 4. Confidence calibration

The naive model is **more confident when it's wrong** on the `normal` scenario (Δ = −0.12). Structured confidence is higher (0.80–0.96 vs 0.29–0.46) and tracks correctness — the actionable signal a production system needs.

### 5. Determinism

The state builder is fully deterministic — verified across 40 seeds, 0 false positives, 100% reproducibility. The LLM reasons over facts, not impressions.

---

## Architecture

```
core/                 Universal data models + abstractions
  temporal_context.py     TemporalContext, Event, Trend, Segment, Period
  schemas.py              Signal, StructuredDecision, ApprovedAction
  base_adapter.py         DomainAdapter abstract interface
  reasoning_agent.py      Pipeline orchestration + retry logic

llm/                  LLM provider abstraction
  base.py                 BaseLLM abstract class
  ollama.py               Local inference (Llama 3, Qwen 2.5)  ✅ implemented
  openai.py               Cloud inference (GPT-4)              ⬜ skeleton

adapters/             Domain adapters
  sre/                    ✅ FULLY IMPLEMENTED
    signals.py              OpenTelemetry SDK simulator (cpu_spike, memory_leak,
                            latency_degradation, normal) + parse_sre_signals stub
    state.py                Deterministic state builder (trend, events, segments,
                            period, summary)
    output.py               RCADecision schema, build_prompt, parse_output
  markets/                 ⬜ signals done, state/output are skeletons

main.py               CLI (run, list-scenarios, serve)
scripts/              Benchmark + stress-test harnesses
  eval_benchmark.py       Structured vs naive evaluation
  stress_test.py          Prolonged pipeline stress testing
data/                 Scenario configurations
api/, routes/, demo/  ⬜ Skeletons (FastAPI + Streamlit) — second pass
tests/                ⬜ Test skeletons
```

---

## Getting started

> Requires Python 3.11 and a running Ollama server with `qwen2.5` (recommended, 32K context) or `llama3`.

```bash
pip install -r requirements.txt
```

Run the CLI (the `stratum` package lives at the repo root; run from its parent directory):

```bash
# List scenarios
cd .. && PYTHONPATH=. python3 -m stratum.main list-scenarios

# Run a scenario through the full pipeline (local Ollama inference)
cd .. && PYTHONPATH=. python3 -m stratum.main run sre --scenario cpu_spike --llm qwen2.5

# Run the naive-vs-structured benchmark
cd .. && PYTHONPATH=. python3 -m stratum.scripts.eval_benchmark \
  --runs 5 --scenarios all --mode both --llm qwen2.5

# Add the red-herring messiness test
cd .. && PYTHONPATH=. python3 -m stratum.scripts.eval_benchmark \
  --runs 5 --scenarios all --messy --mode both --llm qwen2.5

# Reproduce the token-compression number
cd .. && PYTHONPATH=. python3 -m stratum.scripts.eval_benchmark \
  --runs 1 --scenarios cpu_spike --signal-count 100000 --mode both
```

> **Note:** `PYTHONPATH=.` must point at the directory *containing* the `stratum` folder.

---

## The core pipeline

```python
from stratum.llm.ollama import OllamaLLM
from stratum.adapters.sre.output import SREAdapter
from stratum.core.reasoning_agent import ReasoningAgent
from stratum.data.sre.scenarios import generate_scenario_signals

adapter = SREAdapter()
llm = OllamaLLM(model="qwen2.5")
agent = ReasoningAgent(adapter=adapter, llm=llm)

signals = generate_scenario_signals("cpu_spike")
decision, trace = agent.reason_with_trace(signals)

print(decision.analysis)
print(decision.confidence)
print(decision.suggested_actions)
# trace contains: signal_count, the TemporalContext, the exact prompt,
# and the raw LLM response — full observability.
```

---

## Design principles

1. **State-first design** — never feed raw signals to an LLM directly
2. **Hybrid reasoning** — deterministic computation + LLM reasoning
3. **Modular adapters** — one core, any domain
4. **Traceable output** — you can always print the state and see exactly what happened
5. **No framework lock-in** — plain Python + numpy, no LangChain

---

## Status

**SRE MVP**: ✅ complete and benchmarked.

**In progress**: markets adapter (signals done), FastAPI routes, Streamlit demo, full test suite, real-data ingestion (`parse_sre_signals`).

The next milestone is exposing the pipeline via FastAPI and a Streamlit demo with full reasoning-trace visibility.