"""
stratum/api/main.py

FastAPI application entry point for Stratum.
Exposes the reasoning pipeline as REST API endpoints.
"""

import logging
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from stratum.llm.ollama import OllamaLLM
from stratum.adapters.sre.output import SREAdapter
from stratum.adapters.markets.output import MarketAdapter
from stratum.core.reasoning_agent import ReasoningAgent

logger = logging.getLogger(__name__)


def create_app(
    llm_model: str = "llama3",
    llm_base_url: str = "http://localhost:11434",
) -> FastAPI:
    """
    Factory that builds the FastAPI application.

    Steps to implement:
    1. Create the FastAPI instance with title="Stratum API",
       version="0.1.0", description="Domain-agnostic temporal reasoning framework"
    2. Add CORS middleware (allow all origins for local demo)
    3. Instantiate the LLM: OllamaLLM(model=llm_model, base_url=llm_base_url)
       (Optionally fall back to OpenAILLM if model starts with "gpt-")
    4. Instantiate adapters:
       sre_adapter = SREAdapter()
       market_adapter = MarketAdapter()
    5. Create ReasoningAgents:
       sre_agent = ReasoningAgent(adapter=sre_adapter, llm=llm)
       market_agent = ReasoningAgent(adapter=market_adapter, llm=llm)
    6. Attach agents to app.state so route modules can access them:
       app.state.sre_agent = sre_agent
       app.state.market_agent = market_agent
    7. Import and include routers from app.routes:
       from stratum.routes.sre import router as sre_router
       from stratum.routes.markets import router as markets_router
       app.include_router(sre_router, prefix="/api/sre")
       app.include_router(markets_router, prefix="/api/markets")

    8. Add a health check endpoint:
       @app.get("/health")
       def health() -> dict:
           return {"status": "ok", "llm_model": llm_model}

    Returns:
        FastAPI app ready to run with uvicorn.
    """
    ...


# Module-level app for `uvicorn stratum.api.main:app`
app = create_app()