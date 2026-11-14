"""Cache LLM results keyed by a hash of (inputs, prompt version, model)."""

import hashlib
import json
from collections.abc import Callable

from pydantic import BaseModel

from aqstudio.llm.client import LLMClient
from aqstudio.llm.prompts.actions import PROMPT_VERSION as ACTIONS_VERSION
from aqstudio.llm.prompts.advisory import PROMPT_VERSION as ADVISORY_VERSION
from aqstudio.llm.prompts.interpret import PROMPT_VERSION as INTERPRET_VERSION
from aqstudio.schemas import ActionDraft, AdvisoryDraft, ClaimDraft, Fact, Persona
from aqstudio.store.db import Database


def cache_key(**material: object) -> str:
    """Stable hash of everything that determines an output."""
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode()).hexdigest()


class CachedLLMClient:
    """Wraps an LLMClient; identical inputs reuse the stored result instead of a new API call."""

    def __init__(self, inner: LLMClient, db: Database, model: str) -> None:
        """Store the wrapped client, the database and the model name used in cache keys."""
        self._inner = inner
        self._db = db
        self._model = model

    def _cached[M: BaseModel](
        self, key: str, schema: type[M], compute: Callable[[], list[M]]
    ) -> list[M]:
        """Return the cached list for a key, or compute and store it."""
        hit = self._db.cache_get(key)
        if hit is not None:
            return [schema.model_validate(item) for item in json.loads(hit)]
        items = compute()
        self._db.cache_put(key, json.dumps([i.model_dump(mode="json") for i in items]))
        return items

    def _key(self, kind: str, version: str, facts: list[Fact], **extra: object) -> str:
        return cache_key(
            kind=kind,
            prompt=version,
            model=self._model,
            facts=[f.model_dump(mode="json") for f in facts],
            **extra,
        )

    def interpret_facts(
        self, facts: list[Fact], persona: Persona, context: str | None
    ) -> list[ClaimDraft]:
        """Claims, cached by inputs."""
        key = self._key("claims", INTERPRET_VERSION, facts, persona=persona.value, context=context)
        return self._cached(
            key, ClaimDraft, lambda: self._inner.interpret_facts(facts, persona, context)
        )

    def rank_actions(
        self, facts: list[Fact], persona: Persona, context: str | None
    ) -> list[ActionDraft]:
        """Actions, cached by inputs."""
        key = self._key("actions", ACTIONS_VERSION, facts, persona=persona.value, context=context)
        return self._cached(
            key, ActionDraft, lambda: self._inner.rank_actions(facts, persona, context)
        )

    def write_advisory(self, facts: list[Fact], level: str) -> AdvisoryDraft:
        """Advisory, cached by inputs."""
        key = self._key("advisory", ADVISORY_VERSION, facts, level=level)
        [draft] = self._cached(
            key, AdvisoryDraft, lambda: [self._inner.write_advisory(facts, level)]
        )
        return draft
