"""
stratum/llm/base.py

Abstract base class for LLM providers. All LLM implementations (Ollama,
OpenAI, etc.) must implement the generate() method.
"""

from abc import ABC, abstractmethod


class BaseLLM(ABC):
    """
    Abstract interface for LLM providers.

    Every provider (Ollama, OpenAI, Anthropic, etc.) implements this
    contract so the framework can swap models without changing any
    other code.
    """

    @abstractmethod
    def generate(self, prompt: str, **kwargs) -> str:
        """
        Send a single prompt to the LLM and return the text response.

        Args:
            prompt: The full prompt string to send.
            **kwargs: Provider-specific parameters that override
                      constructor defaults, e.g. temperature, max_tokens.

        Returns:
            str — the LLM's complete text response.
                   Never raise on network errors; return an "ERROR: ..."
                   string instead so the ReasoningAgent retry loop
                   can handle failures gracefully.
        """
        ...