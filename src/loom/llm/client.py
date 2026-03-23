from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class LLMClient:
    model: str
    max_concurrent: int = 10
    _sem: asyncio.Semaphore = field(init=False)

    def __post_init__(self) -> None:
        self._sem = asyncio.Semaphore(self.max_concurrent)

    async def complete(self, *, prompt: str, model: str | None = None) -> str:
        # LiteLLM supports async completion via acompletion.
        import litellm  # type: ignore

        m = model or self.model
        async with self._sem:
            res = await litellm.acompletion(
                model=m,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )

        try:
            return res.choices[0].message.content  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("Unexpected LiteLLM response structure (%s) — falling back to str(res)", exc)
            return str(res)
