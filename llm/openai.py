"""
stratum/llm/openai.py

OpenAI LLM implementation for cloud-based inference (GPT-4, GPT-3.5).
"""

import json
import logging
import os
from typing import Optional

from openai import OpenAI

from stratum.llm.base import BaseLLM

logger = logging.getLogger(__name__)


class OpenAILLM(BaseLLM):
    """
    LLM provider for the OpenAI API.

    Usage:
        llm = OpenAILLM(model="gpt-4", api_key="sk-...")
        response = llm.generate("Analyze this...")
    """

    def __init__(
        self,
        model: str = "gpt-4",
        api_key: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
        timeout: int = 60,
    ):
        """
        Args:
            model: OpenAI model name, e.g. "gpt-4", "gpt-3.5-turbo"
            api_key: OpenAI API key. Falls back to OPENAI_API_KEY env var.
            temperature: Sampling temperature — lower = more deterministic
            max_tokens: Maximum response length
            timeout: HTTP request timeout in seconds

        Raises:
            ValueError: If no API key is provided and OPENAI_API_KEY is not set.
        """
        self.model = model
        api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OpenAI API key required. Pass as api_key or set OPENAI_API_KEY env var."
            )
        self.client = OpenAI(api_key=api_key, timeout=timeout)
        self.temperature = temperature
        self.max_tokens = max_tokens

    def generate(self, prompt: str, **kwargs) -> str:
        """
        Send a prompt to OpenAI and return the text response.

        Steps to implement:
        1. Use self.client.chat.completions.create(...)
           - model: from kwargs or self.model
           - messages: [system msg instructing precise reasoning engine, user msg with prompt]
           - temperature: from kwargs or self.temperature
           - max_tokens: from kwargs or self.max_tokens

        2. Extract and return response.choices[0].message.content or ""

        Error handling (never raise):
        - Any exception → log with logger.error and return f"ERROR: {e}"

        Tip: The system prompt should instruct the LLM to:
             "You are a precise reasoning engine. Analyze the provided
              context and produce structured analysis. Be concise and accurate."
        """
        ...