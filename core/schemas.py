"""
stratum/core/schemas.py

Shared Pydantic schemas for signals, decisions, and actions.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Signal(BaseModel):
    """A single data point from a signal stream."""
    timestamp: datetime
    name: str
    value: float
    unit: str = ""
    tags: dict = Field(default_factory=dict)


class StructuredDecision(BaseModel):
    """A structured output from the LLM after reasoning over a TemporalContext."""
    domain: str
    analysis: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    suggested_actions: list[str] = Field(default_factory=list)
    reasoning_trace: str = ""
    raw_llm_response: str = ""


class ApprovedAction(BaseModel):
    """An action that has passed through the ActionGate."""
    action_type: str
    target: str
    parameters: dict = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    approved_by: str = "action_gate"