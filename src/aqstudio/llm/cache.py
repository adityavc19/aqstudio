"""Cache LLM results keyed by a hash of (inputs, prompt version, model)."""

import hashlib
import json
import time

from aqstudio.llm.client import LLMClient
from aqstudio.llm.prompts.interpret import PROMPT_VERSION
from aqstudio.schemas import (
    ClaimDraft,
    Fact,
    Persona,
)
from aqstudio.store.db import Database


class CachedLLMClient:
    """Wraps an LLMClient; identical inputs reuse the stored result instead of a new API call."""

    def __init__(self, inner: LLMClient, db: Database, model: str) -> None:
        """Store the wrapped client, the database and the model name used in cache keys."""
        self._inner = inner
        self._db = db
        self._model = model

    def interpret_facts(
        self, facts: list[Fact], persona: Persona, context: str | None
    ) -> list[ClaimDraft]:
        """Return cached claims when the same inputs were interpreted before."""
        material = json.dumps(
            {
                "facts": [f.model_dump(mode="json") for f in facts],
                "persona": persona.value,
                "context": context,
                "prompt": PROMPT_VERSION,
                "model": self._model,
            },
            sort_keys=True,
        )
        key = hashlib.sha256(material.encode()).hexdigest()
        with self._db.connect() as conn:
            row = conn.execute("SELECT value FROM llm_cache WHERE key = ?", (key,)).fetchone()
        if row is not None:
            return [ClaimDraft.model_validate(c) for c in json.loads(row[0])]
        claims = self._inner.interpret_facts(facts, persona, context)
        with self._db.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO llm_cache (key, value, created_at) VALUES (?, ?, ?)",
                (key, json.dumps([c.model_dump(mode="json") for c in claims]), time.time()),
            )
        return claims
