"""Structured Harness2 editor through the same isolated OpenCode runtime."""
from __future__ import annotations

import json

from app.models import ModelError
from app.runtime.opencode import OpenCodeActor


class _NoTools:
    async def call(self, name, arguments):
        raise ModelError("editor_finance_tools_forbidden")


class OpenCodeEditor:
    """One reserved provider request per Harness2 stage; no hidden retries."""
    def __init__(self, config, *, binary=None):
        self.config = config
        self.actor = OpenCodeActor(config, binary=binary, mode="editor", max_iterations=1,
                                   timeout_seconds=150)

    async def complete(self, system: str, prompt: str) -> dict:
        result = await self.actor.run(json.loads(prompt), system, _NoTools(),
                                      allowed_tools=frozenset(), max_model_calls=1)
        return {"output": result["output"], "evidence": result["evidence"]}
