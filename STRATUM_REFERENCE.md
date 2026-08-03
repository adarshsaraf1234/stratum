# Stratum — Complete Script Reference

> **What every file does, why it exists, and how it fits together.**

---

## Project Purpose

Stratum is a **domain-agnostic temporal reasoning framework**. It ingests raw time-series signals (logs, metrics, prices), builds a deterministic structured state called **TemporalContext**, and passes it to an LLM for reasoning. The output is a **StructuredDecision** with analysis, confidence, and suggested actions.

**Core insight:** Never feed raw logs to an LLM. First build structured state, then reason over it.

---

## Architecture Flow

```
Raw Data (JSON/CSV/mock)
       │
       ▼
┌──────────────────────────────────────────────────────┐
│  CORE: Schemas & Data Models                         │
│  core/temporal_context.py                            │
│  core/schemas.py                                     │
│  core/base_adapter.py                                │
│  core/reasoning_agent.py                             │
└──────────────────────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────────────────────────────┐
│  LLM LAYER: Model Abstraction                        │
│  llm/base.py                                         │
│  llm/ollama.py                                       │
│  llm/openai.py                                       │
└──────────────────────────────────────────────────────┘
       │
       ├─────────────────────────────┐
       ▼                             ▼
┌─────────────────┐     ┌─────────────────────┐
│ SRE ADAPTER     │     │ MARKETS ADAPTER     │
│ sre/signals.py  │     │ markets/signals.py  │
│ sre/state.py    │     │ markets/state.py    │
│ sre/output.py   │     │ markets/output.py   │
└─────────────────┘     └─────────────────────┘
       │                             │
       └──────────┬──────────────────┘
                  ▼
┌──────────────────────────────────────────────────────┐
│  API + DEMO                                          │
│  api/main.py          ← FastAPI server              │
│  routes/sre.py        ← SRE endpoints               │
│  routes/markets.py    ← Markets endpoints            │
│  demo/ui.py           ← Streamlit UI                │
│  main.py              ← CLI entry point             │
└──────────────────────────────────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────────────────┐
│  DATA + TESTS                                        │
│  data/sre/scenarios.py      ← Mock SRE incidents    │
│  data/markets/scenarios.py  ← Mock market scenarios │
│  tests/                     ← Unit + integration    │
└──────────────────────────────────────────────────────┘
```

---

## Phase 1: Core — Data Models & Abstractions

These are the files that define the framework's "language" — the data structures that every other component builds on.

| # | File | Lines | Status | What it does |
|---|------|-------|--------|-------------|
| 1 | `core/temporal_context.py` | 66 | ✅ **WRITTEN** | Defines **4 data classes**: `Event` (a salient event in time), `Trend` (direction + rate of change), `Segment` (a labeled time window slice), and `TemporalContext` (the universal container that bundles events + trend + segments + summary). Includes helper properties like `is_normal()`, `high_severity_events`, `window_duration_seconds`. This is **the most important file in the entire project** — every adapter builds a TemporalContext, and every reasoning agent reasons over one. |
| 2 | `core/schemas.py` | 37 | ✅ **WRITTEN** | Defines **3 data classes**: `Signal` (a single timestamped data point with name, value, unit, tags), `StructuredDecision` (the LLM's output: analysis text, confidence score between 0–1, suggested actions, reasoning trace, and raw LLM response), and `ApprovedAction` (an action that has passed through the ActionGate with type, target, parameters, and approval metadata). These are the inputs and outputs of the pipeline. |
| 3 | `core/base_adapter.py` | 0 | ❌ **EMPTY** | Defines the **`DomainAdapter` abstract class** — an interface contract that every domain adapter must implement. It specifies 4 methods: `parse_signals()` to convert raw data into `list[Signal]`, `build_state()` to convert signals into `TemporalContext`, `build_prompt()` to convert context into an LLM prompt string, and `parse_output()` to convert LLM text into structured dict. This is what makes the framework domain-agnostic. |
| 4 | `core/reasoning_agent.py` | 0 | ❌ **EMPTY** | Defines **`ReasoningAgent`** — the orchestration class that wires everything together. It takes a `DomainAdapter` + `BaseLLM`, exposes a `reason()` method that runs the full pipeline (signals → state → prompt → LLM → decision), and a `reason_with_trace()` method that also returns the intermediate TemporalContext and prompt for debugging. Includes retry logic (configurable max_retries). |

---

## Phase 2: LLM Layer — Model Abstraction

These files abstract away the LLM provider so the framework can work with Ollama (local) or OpenAI (cloud) interchangeably.

| # | File | Lines | Status | What it does |
|---|------|-------|--------|-------------|
| 5 | `llm/base.py` | 0 | ❌ **EMPTY** | Defines **`BaseLLM`** abstract class with a single abstract method: `generate(prompt: str) → str`. Every LLM provider (Ollama, OpenAI, etc.) implements this contract. Enables swapping models without changing any other code. |
| 6 | `llm/ollama.py` | 0 | ❌ **EMPTY** | Implements **`OllamaLLM`** — sends prompts to a locally running Ollama instance via HTTP (`POST /api/generate`). Configurable: model name (e.g. `llama3`, `qwen2.5`), base URL, temperature, max tokens, and timeout. Includes `list_models()` to query available models, and graceful error handling for connection failures and timeouts. |
| 7 | `llm/openai.py` | 0 | ❌ **EMPTY** | Implements **`OpenAILLM`** — sends prompts to the OpenAI API using the official Python SDK. Configurable: model name (e.g. `gpt-4`), API key (from parameter or `OPENAI_API_KEY` env var), temperature, and max tokens. Uses a system prompt that instructs the model to be a "precise reasoning engine." |

---

## Phase 3: SRE Adapter — Infrastructure Incident RCA

These files implement the first domain adapter: **Site Reliability Engineering**. Takes infrastructure metrics (CPU, memory, latency), detects incidents, and produces RCA reports.

| # | File | Lines | Status | What it does |
|---|------|-------|--------|-------------|
| 8 | `adapters/sre/signals.py` | 0 | ❌ **EMPTY** | Generates **mock SRE signals** — time-series data simulating real infrastructure metrics. Has `generate_incident_signals()` with 4 incident types: `cpu_spike` (CPU jumps to 95%+), `memory_leak` (memory grows linearly from 50% to 95%), `latency_degradation` (P99 latency climbs from 100ms to 2000ms), `normal` (everything stable). Outputs `list[Signal]` with deterministic randomness (seeded). Also includes `parse_sre_signals()` for converting JSON/CSV input into `Signal` objects. |
| 9 | `adapters/sre/state.py` | 0 | ❌ **EMPTY** | Implements the **SRE state builder** — the core deterministic logic. Takes `list[Signal]`, groups by metric name, computes: **trend** (linear regression slope for CPU, memory, latency independently), **events** (threshold breaches: CPU > 85%, memory > 90%, latency > 500ms SLA), **segments** (rolling variance change-point detection), and generates a plain-English **summary**. Outputs a `TemporalContext` with `domain="sre"`. |
| 10 | `adapters/sre/output.py` | 0 | ❌ **EMPTY** | Defines **SRE-specific output schemas** and the **prompt builder**. Contains `RCADecision` (a `StructuredDecision` subclass with root_cause, severity, affected_services, remediation_steps) and `SREPromptBuilder` which constructs the LLM prompt — includes the TemporalContext summary, instructions to identify root cause, and the expected JSON output format. Also contains `parse_sre_output()` to extract structured RCA from the LLM's text response. |

---

## Phase 4: Markets Adapter — Financial Regime Detection

The second domain adapter: **Financial Markets**. Takes price/volume data, detects market regimes and anomalies, and produces signal reports.

| # | File | Lines | Status | What it does |
|---|------|-------|--------|-------------|
| 11 | `adapters/markets/signals.py` | 0 | ❌ **EMPTY** | Generates **mock market signals** — time-series data simulating stock/ETF behavior. Has `generate_market_signals()` with 4 scenario types: `bull_run` (price trending up +5% with high volume), `crash` (price drops 8%+ with spike in volume), `consolidation` (price ranges ±1%, low volume), and `normal` (mild upward drift, average volume). Also includes `parse_market_signals()` for Yahoo Finance / Alpaca API data. Each signal has name="price" or "volume", with ticker symbol in tags. |
| 12 | `adapters/markets/state.py` | 0 | ❌ **EMPTY** | Implements the **Markets state builder**. Takes `list[Signal]`, separates price vs volume, computes: **trend** (price slope as % change, volume trend), **events** (regime changes: breakouts above/below 20-period moving average, volume spikes > 2× average, support/resistance breaks), **segments** (up-trend, down-trend, ranging). Determines **period** (detects ~daily cycles in volume). Outputs a `TemporalContext` with `domain="markets"` and metadata containing ticker, current_price, price_range. |
| 13 | `adapters/markets/output.py` | 0 | ❌ **EMPTY** | Defines **Market-specific output schemas** and prompt builder. Contains `SignalReport` (a `StructuredDecision` subclass with regime, signal_strength, price_target_range, key_levels, volume_analysis) and `MarketPromptBuilder` which constructs the prompt — instructs the LLM to identify the current market regime, explain price action, assess signal strength, and note key support/resistance levels. Includes `parse_market_output()` for extracting structured reports. |

---

## Phase 5: Data — Mock Scenarios

These files provide the test scenarios that make the demo work. No LLM needed to verify — these are just deterministic input data.

| # | File | Lines | Status | What it does |
|---|------|-------|--------|-------------|
| 14 | `data/sre/scenarios.py` | — | ❌ **MISSING** | Defines a dictionary of **SRE demo scenarios** — named incident configurations that `generate_incident_signals()` accepts. Contains entries like `"cpu_spike" → {"incident_type": "cpu_spike", "duration_minutes": 30, ...}`, `"memory_leak"`, `"latency_degradation"`, `"normal"`. Also includes `get_scenario(name)` helper and `list_scenarios()` to enumerate available scenarios. |
| 15 | `data/markets/scenarios.py` | — | ❌ **MISSING** | Same pattern for markets — a dictionary of **market demo scenarios**: `"bull_run"`, `"crash"`, `"consolidation"`, `"normal"`. Includes `get_scenario(name)` and `list_scenarios()` helpers. |

---

## Phase 6: API Layer — FastAPI Server

Exposes Stratum's reasoning pipeline as REST API endpoints.

| # | File | Lines | Status | What it does |
|---|------|-------|--------|-------------|
| 16 | `api/main.py` | — | ❌ **MISSING** | Creates the **FastAPI application**. Initializes the LLM (Ollama by default), instantiates both adapters (SRE and Markets), creates `ReasoningAgent` instances for each, registers route handlers from `routes/`, and configures CORS middleware for the Streamlit demo. Exposes `GET /health` for health checks. Runs with `uvicorn` on port 8000. |
| 17 | `routes/sre.py` | 0 | ❌ **EMPTY** | Defines SRE-related **FastAPI route handlers**. Endpoints: `POST /api/sre/analyze` (accepts scenario name or raw data, returns `StructuredDecision` with RCA), `GET /api/sre/scenarios` (lists available SRE demo scenarios), `POST /api/sre/analyze/trace` (returns decision + full reasoning trace for debugging). |
| 18 | `routes/markets.py` | 0 | ❌ **EMPTY** | Defines Market-related **route handlers**. Endpoints: `POST /api/markets/analyze` (accepts ticker + scenario, returns `StructuredDecision` with signal report), `GET /api/markets/scenarios` (lists available market scenarios), `POST /api/markets/analyze/trace` (returns decision + trace). |

---

## Phase 7: Demo UI — Streamlit

The portfolio-facing demo. Lets users pick an adapter, feed it a scenario, and see the full pipeline output with reasoning trace visible.

| # | File | Lines | Status | What it does |
|---|------|-------|--------|-------------|
| 19 | `demo/ui.py` | 0 | ❌ **EMPTY** | A **Streamlit 4-panel demo application**. **Panel 1** (sidebar): adapter selector (SRE / Markets), scenario dropdown, "Run Analysis" button. **Panel 2** (main): shows the `StructuredDecision` output — analysis text, confidence score (with color coding: green > 0.7, yellow > 0.4, red < 0.4), suggested actions list. **Panel 3** (collapsible): shows the intermediate `TemporalContext` state as formatted JSON — events, trend, segments. **Panel 4** (collapsible): shows the full reasoning trace including the exact prompt sent to the LLM and the raw response. The reasoning trace visibility is the killer feature — it proves the system is interpretable. |

---

## Phase 8: CLI & Tests

| # | File | Lines | Status | What it does |
|---|------|-------|--------|-------------|
| 20 | `main.py` | 0 | ❌ **EMPTY** | **CLI entry point** — simple command-line interface for running Stratum without the API or UI. Supports `stratum run sre --scenario cpu_spike` (processes a scenario and prints decision), `stratum run markets --scenario crash`, `stratum list-scenarios`, and `stratum serve` (starts the FastAPI server). Uses Python's `argparse` for argument parsing. |
| 21 | `tests/test_temporal_context.py` | — | ❌ **MISSING** | **Unit tests for the core data structures**. Tests: creating a TemporalContext with events, computing `is_normal()` correctly, filtering `high_severity_events`, serializing/deserializing to/from JSON, and edge cases (empty events list, missing optional fields, negative durations). |
| 22 | `tests/test_state_builders.py` | — | ❌ **MISSING** | **Integration tests for state builders**. Tests: SRE state builder correctly detects CPU spikes (generates signals → builds state → asserts events contain "threshold_breach"), market state builder detects bull runs, trend computation matches expected slopes, segment detection splits windows correctly, summary generation is non-empty. Uses pytest. |
| 23 | `requirements.txt` | — | ❌ **MISSING** | **Python dependencies** — `pydantic>=2.0`, `fastapi>=0.100`, `uvicorn[standard]`, `streamlit>=1.20`, `requests>=2.0`, `openai>=1.0`, `numpy>=1.24`, `pytest>=7.0`. |

---

## Stale / Dead Files

These files exist from a previous prototyping session and should be cleaned up.

| File | Lines | What's wrong |
|------|-------|-------------|
| `core /temporal_context.py` | 26 | Directory name has a **space** in it (`core /`). This is an earlier, incomplete version of temporal_context.py (missing Trend, Segment, Period fields, uses `optional` instead of `Optional`). **Should be deleted** — the real file is `core/temporal_context.py`. |

---

## What Each Phase Unlocks

| Phase | Files | What you can do after building it |
|-------|-------|-----------------------------------|
| Phase 1 | `core/*.py` | ✅ **DONE** — You can create TemporalContext objects, signals, and decisions. No LLM needed yet. |
| Phase 2 | `llm/*.py` | Run LLM inference locally (Ollama) or via cloud (OpenAI). |
| Phase 3 | `adapters/sre/*.py` | Generate SRE signals → build TemporalContext → get RCA from LLM. **First full pipeline.** |
| Phase 4 | `adapters/markets/*.py` | Same pipeline for financial data. **Proves the adapter pattern works.** |
| Phase 5 | `data/*/scenarios.py` | Pre-built demo scenarios for both adapters. No manual data entry needed. |
| Phase 6 | `api/main.py`, `routes/*.py` | REST API — send HTTP requests, get structured decisions back. |
| Phase 7 | `demo/ui.py` | **Portfolio-ready Streamlit demo** with full trace visibility. The thing you show in interviews. |
| Phase 8 | `main.py`, `tests/*.py` | CLI for quick testing + tests that prove the system works correctly. |

---

## Build Order (Recommended)

```
Phase 1 → Phase 2 → Phase 3 → Phase 5 → Phase 4 → Phase 6 → Phase 7 → Phase 8
   ↑         ↑         ↑         ↑         ↑
   │         │         │         │         └── Markets builds on proven pattern
   │         │         │         └── Scenarios feed both adapters
   │         │         └── First proof of life (signals → context → LLM → decision)
   │         └── Needed before Phase 3
   └── Already done — start here
```

The key milestone is **Phase 3 completion**: when you can run SRE signals → TemporalContext → LLM → RCA output, the framework is real. Everything after that is repetition and polish.