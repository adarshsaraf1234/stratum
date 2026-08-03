# Stratum

A **domain-agnostic temporal reasoning framework** — understand why complex systems behave the way they do.

```
Signals → TemporalContext → ReasoningAgent → StructuredDecision
```

## What it does

Stratum ingests raw time-series signals (infrastructure metrics, stock prices, IoT sensors), builds a deterministic structured state called **TemporalContext** (events, trends, segments, summary), and passes it to an LLM for structured reasoning — instead of feeding raw data to an LLM and hoping for a good answer.

## Included adapters

| Adapter | Domain | Input | Output |
|---------|--------|-------|--------|
| SRE | Infrastructure incidents | CPU, memory, latency metrics | Root cause analysis (RCA) |
| Markets | Financial markets | Price, volume data | Regime detection + signal report |

## Architecture

```
core/          Universal data models + abstractions
  temporal_context.py   TemporalContext, Event, Trend, Segment
  schemas.py            Signal, StructuredDecision, ApprovedAction
  base_adapter.py       DomainAdapter abstract interface
  reasoning_agent.py    Pipeline orchestration + retry logic

llm/           LLM provider abstraction
  base.py               BaseLLM abstract class
  ollama.py             Local inference (Llama 3, Qwen 2.5)
  openai.py             Cloud inference (GPT-4)

adapters/      Domain adapters
  sre/                  Signals → SRE TemporalContext → RCA output
  markets/              Signals → Market TemporalContext → SignalReport

api/           FastAPI server
routes/        REST endpoints (analyze, analyze/trace, scenarios)
demo/          Streamlit 4-panel demo with full reasoning trace
data/          Mock demo scenarios for both adapters
tests/         Unit + integration test skeletons
```

## Getting started

```bash
pip install -r requirements.txt

# Run the CLI (requires Ollama running locally)
python -m stratum run sre --scenario cpu_spike
python -m stratum run markets --scenario crash

# Serve the API
uvicorn stratum.api.main:app --reload

# Run the Streamlit demo
streamlit run stratum/demo/ui.py

# Run tests
pytest
```

## Design principles

1. **State-first design** — never feed raw signals to an LLM directly
2. **Hybrid reasoning** — deterministic computation + LLM reasoning
3. **Modular adapters** — one core, any domain
4. **Traceable output** — you can always print the state and see what happened
5. **No framework lock-in** — plain Python, no LangChain