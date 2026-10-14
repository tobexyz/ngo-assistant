"""Smoke tests against the real docker compose stack (Ollama + pgvector).

Deselected by default (`addopts = "-m 'not integration'"`); run with
`pytest -m integration` after `docker compose up -d` and scripts/pull-models.sh.

CPU-only: the first chat call loads the model and can take a minute or more.
Prompts are kept to one line so each call stays short; if you add a
pytest-timeout later, allow generously (e.g. 300 s per test).
"""

import os

import pytest

from ngo_assistant.llm import LLMClient

pytestmark = pytest.mark.integration


def test_real_chat_returns_text_and_token_counts():
    llm = LLMClient()  # NGO_CHAT_MODEL / OLLAMA_HOST from env, with defaults
    result = llm.chat([{"role": "user", "content": "Reply with one short word: hello."}])
    assert result.text.strip()
    assert result.usage.input_tokens > 0
    assert result.usage.output_tokens > 0
    assert result.usage.model_calls == 1


def test_real_embed_returns_equal_length_vectors_and_tokens():
    llm = LLMClient()
    result = llm.embed(["Klimaschutz", "climate protection"])
    assert len(result.vectors) == 2
    assert len(result.vectors[0]) > 0
    assert len(result.vectors[0]) == len(result.vectors[1])
    # bge-m3 has 1024 dimensions (docs/tech.md section 5, HF model card). Override with NGO_EMBED_DIM
    # when NGO_EMBED_MODEL is changed to another embedding model.
    assert len(result.vectors[0]) == int(os.environ.get("NGO_EMBED_DIM", "1024"))
    assert result.usage.embed_tokens > 0
    assert result.usage.model_calls == 1


def test_postgres_has_vector_extension():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not set; cannot reach the pgvector Postgres")
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(url, connect_timeout=10) as conn:
        row = conn.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'").fetchone()
    assert row == ("vector",)
