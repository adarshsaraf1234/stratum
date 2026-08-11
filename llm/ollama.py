"""
stratum/llm/ollama.py

Ollama LLM implementation for local model inference (Llama 3, Qwen 2.5).
"""

import json
import logging
from typing import Optional

import requests

from stratum.llm.base import BaseLLM

logger = logging.getLogger(__name__)


class OllamaLLM(BaseLLM):
    """
    LLM provider for locally running Ollama models.

    Usage:
        llm = OllamaLLM(model="llama3", temperature=0.3)
        response = llm.generate("Explain this incident...")
    """

    def __init__(
        self,
        model: str = "llama3",
        base_url: str = "http://localhost:11434",
        temperature: float = 0.1,
        max_tokens: int = 2048,
        timeout: int = 60,
    ):
        """
        Args:
            model: Ollama model name, e.g. "llama3", "qwen2.5"
            base_url: Ollama server URL (default localhost:11434)
            temperature: Sampling temperature — lower = more deterministic
            max_tokens: Maximum response length
            timeout: HTTP request timeout in seconds
        """
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def generate(self, prompt: str, **kwargs) -> str:
        """
        Send a prompt to Ollama and return the text response.

        Steps to implement:
        1. Build the request URL: {base_url}/api/generate
        2. Build the JSON payload:
           {
               "model": self.model,
               "prompt": prompt,
               "temperature": from kwargs or self.temperature,
               "max_tokens": from kwargs or self.max_tokens,
               "stream": False,      # we want the full response
           }
        3. POST via requests.post(url, json=payload, timeout=self.timeout)
        4. Validate status code (raise_for_status)
        5. Return result["response"]

        Error handling (never raise):
        - ConnectionError      → return "ERROR: Cannot connect to Ollama..."
        - Timeout              → return "ERROR: Ollama request timed out."
        - KeyError/StatusError → return "ERROR: {e}"

        Log each request with logger.info (model + prompt length).
        """
        try :
            url = f"{self.base_url}/api/generate"
            payload = {
                "model": self.model,
                "prompt": prompt,
                "temperature": kwargs.get("temperature", self.temperature),
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                "stream": False,
            }
            # logger.info("Ollama request: model=%s, prompt_length=%d", self.model, len(prompt))
            response = requests.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            result = response.json()
            if result == 200:
                return result.get("response", "")
            else:
                logger.error("Ollama returned unexpected status: %s", result)
                return f"ERROR: Unexpected response from Ollama: {result}"
        except requests.exceptions.ConnectionError:
            logger.error("Cannot connect to Ollama at %s", self.base_url)
            return "ERROR: Cannot connect to Ollama. Is the server running?"
        except requests.exceptions.Timeout:
            logger.error("Ollama request timed out after %d seconds", self.timeout)
            return "ERROR: Ollama request timed out."
        except requests.exceptions.RequestException as e:
            logger.error("Ollama request failed: %s", str(e))
            return f"ERROR: {str(e)}"

    def list_models(self) -> list[str]:
        """
        Query Ollama for available models.

        Steps to implement:
        1. GET {base_url}/api/tags with a short timeout
        2. Parse JSON: response.json()["models"] is a list of dicts
        3. Extract each model's "name" field
        4. Return a list of model name strings

        On failure, log the error and return an empty list.
        """
        try:
            url = f"{self.base_url}/api/tags"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            models = [m["name"] for m in data.get("models", []) if "name" in m]
            return models
        except requests.exceptions.RequestException as e:
            logger.error("Failed to list Ollama models: %s", str(e))
            return []