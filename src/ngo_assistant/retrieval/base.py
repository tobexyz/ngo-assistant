"""The contract every variant implements.

The contract is question in, Answer out, and NOT "retriever" in the narrow sense:
in the agentic variant the model does the retrieval itself via tools,
so there is no separate retriever to swap. See docs/adr/003.
"""

from __future__ import annotations

from typing import Protocol

from ngo_assistant.models import Answer


class Answerer(Protocol):
    name: str

    def answer(self, question: str, language: str) -> Answer:
        """Answer one question using the tenant's sources only."""
        ...
