from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class LLMClient:
    model: str
    max_concurrent: int = 10

    def __post_init__(self) -> None:
        self._sem: asyncio.Semaphore | None = None

    def _get_sem(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(self.max_concurrent)
        return self._sem

    async def complete(self, *, prompt: str, model: str | None = None) -> str:
        # LiteLLM supports async completion via acompletion.
        import litellm  # type: ignore

        m = model or self.model
        async with self._get_sem():
            res = await litellm.acompletion(
                model=m,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )

        return res.choices[0].message.content  # type: ignore[attr-defined]
