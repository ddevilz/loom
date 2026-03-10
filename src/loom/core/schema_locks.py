import asyncio
import logging
import weakref

log = logging.getLogger(__name__)

# WeakValueDictionary ensures locks are reclaimed once no LoomGraph holds a
# reference, preventing unbounded growth.
_SCHEMA_LOCKS: weakref.WeakValueDictionary[str, asyncio.Lock] = (
    weakref.WeakValueDictionary()
)
_SCHEMA_LOCKS_REGISTRY_LOCK = asyncio.Lock()


async def _get_schema_lock(graph_name: str) -> asyncio.Lock:
    """Get or create a schema lock for the given graph name."""
    async with _SCHEMA_LOCKS_REGISTRY_LOCK:
        lock = _SCHEMA_LOCKS.get(graph_name)
        if lock is None:
            lock = asyncio.Lock()
            _SCHEMA_LOCKS[graph_name] = lock
        return lock
