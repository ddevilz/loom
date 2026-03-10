"""Gateway protocol for database abstraction."""

from typing import Any, Protocol


class _Gateway(Protocol):
    """Protocol for database gateway implementations."""

    graph_name: str

    def reconnect(self) -> None: ...

    def run(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ) -> None: ...

    def query_rows(
        self,
        cypher: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ) -> list[dict[str, Any]]: ...
