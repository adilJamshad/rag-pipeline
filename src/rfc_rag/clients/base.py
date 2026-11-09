"""The contract every LLM backend implements."""

from typing import Protocol, runtime_checkable


class LLMError(RuntimeError):
    pass


@runtime_checkable
class LLMBackend(Protocol):
    name: str

    def complete(self, prompt: str, *, max_tokens: int = 800,
                 temperature: float = 0.0) -> str:
        """Return the model's text. Raise LLMError if it produced none."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input, each of config.EMBED_DIM floats."""
