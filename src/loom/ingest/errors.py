from __future__ import annotations

import logging

from loom.ingest.result import IndexError

logger = logging.getLogger(__name__)


def append_index_error(
    errors: list[IndexError],
    *,
    path: str,
    phase: str,
    error: Exception,
) -> None:
    logger.error(
        "Indexing error in phase '%s' for '%s': %s", phase, path, error, exc_info=True
    )
    errors.append(IndexError(path=path, phase=phase, message=str(error)))
