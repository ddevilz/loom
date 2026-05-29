from __future__ import annotations

from collections.abc import Callable

from tree_sitter import Node as TSNode

from loom.indexer.languages._ts_utils import (
    count_node_type,
    has_decorator,
    has_decorator_prefix,
    walk_all,
)

# ---------- Python detectors ----------

def detect_async_generator(n: TSNode, s: bytes) -> str | None:
    return "async generator" if b"async def" in s and b"yield" in s else None


def detect_async_function(n: TSNode, s: bytes) -> str | None:
    return "async function" if b"async def" in s and b"yield" not in s else None


def detect_context_manager(n: TSNode, s: bytes) -> str | None:
    return "context manager" if has_decorator(n, "contextmanager") else None


def detect_generic_type(n: TSNode, s: bytes) -> str | None:
    return "generic type" if any(c.type == "type_parameter" for c in walk_all(n)) else None


def detect_dataclass(n: TSNode, s: bytes) -> str | None:
    return "dataclass" if has_decorator(n, "dataclass") else None


def detect_attrs(n: TSNode, s: bytes) -> str | None:
    return "attrs class" if has_decorator(n, "attrs") or has_decorator(n, "define") else None


def detect_route(n: TSNode, s: bytes) -> str | None:
    return (
        "Flask/FastAPI route"
        if has_decorator_prefix(
            n,
            (
                "app.route",
                "router.",
                "app.get",
                "app.post",
                "app.put",
                "app.delete",
                "app.patch",
            ),
        )
        else None
    )


def detect_cli(n: TSNode, s: bytes) -> str | None:
    return (
        "CLI command"
        if has_decorator_prefix(n, ("click.command", "app.command", "typer.command"))
        else None
    )


def detect_celery(n: TSNode, s: bytes) -> str | None:
    return (
        "Celery task"
        if has_decorator_prefix(n, ("celery.task", "shared_task"))
        else None
    )


def detect_heavy_errors(n: TSNode, s: bytes) -> str | None:
    return "heavy error handling" if count_node_type(n, "try_statement") >= 3 else None


def detect_subprocess(n: TSNode, s: bytes) -> str | None:
    return "subprocess management" if b"subprocess" in s else None


def detect_file_io(n: TSNode, s: bytes) -> str | None:
    return (
        "file I/O"
        if b"open(" in s and any(c.type == "with_statement" for c in walk_all(n))
        else None
    )


PYTHON_PATTERNS: list[Callable[[TSNode, bytes], str | None]] = [
    detect_async_generator,
    detect_async_function,
    detect_context_manager,
    detect_generic_type,
    detect_dataclass,
    detect_attrs,
    detect_route,
    detect_cli,
    detect_celery,
    detect_heavy_errors,
    detect_subprocess,
    detect_file_io,
]

# ---------- TypeScript / JavaScript detectors ----------


def detect_ts_async(n: TSNode, s: bytes) -> str | None:
    return "async/await" if b"async" in s else None


def detect_ts_generator(n: TSNode, s: bytes) -> str | None:
    return "generator" if n.type == "generator_function" else None


def detect_ts_generic(n: TSNode, s: bytes) -> str | None:
    return (
        "generic function"
        if any(c.type == "type_parameters" for c in n.children)
        else None
    )


def _ts_function_name(n: TSNode) -> str:
    name_node = n.child_by_field_name("name")
    if name_node is not None and name_node.text:
        return name_node.text.decode("utf-8", errors="replace")
    return ""


def detect_ts_react_hook(n: TSNode, s: bytes) -> str | None:
    fn_name = _ts_function_name(n)
    return "React hook" if fn_name.startswith("use") and len(fn_name) > 3 else None


TS_PATTERNS: list[Callable[[TSNode, bytes], str | None]] = [
    detect_ts_async,
    detect_ts_generator,
    detect_ts_generic,
    detect_ts_react_hook,
]


PATTERN_DETECTORS: dict[str, list[Callable[[TSNode, bytes], str | None]]] = {
    "python": PYTHON_PATTERNS,
    "typescript": TS_PATTERNS,
    "tsx": TS_PATTERNS,
    "javascript": TS_PATTERNS,
}


def extract_language_notes(
    ts_node: TSNode,
    language: str,
    source: bytes,
) -> str | None:
    """Return concise comma-separated flavor string, or None."""
    detectors = PATTERN_DETECTORS.get(language)
    if not detectors:
        return None
    func_src = source[ts_node.start_byte : ts_node.end_byte]
    notes: list[str] = []
    for d in detectors:
        result = d(ts_node, func_src)
        if result:
            notes.append(result)
    return ", ".join(notes) if notes else None


# ---------- Go detectors ----------


def detect_go_goroutine(n: TSNode, s: bytes) -> str | None:
    return "goroutine" if any(c.type == "go_statement" for c in walk_all(n)) else None


def detect_go_channel(n: TSNode, s: bytes) -> str | None:
    return "channel I/O" if any(c.type == "channel_type" for c in walk_all(n)) else None


def detect_go_error_return(n: TSNode, s: bytes) -> str | None:
    return "error-returning" if b"error" in s else None


GO_PATTERNS: list[Callable[[TSNode, bytes], str | None]] = [
    detect_go_goroutine,
    detect_go_channel,
    detect_go_error_return,
]

# ---------- Rust detectors ----------


def detect_rust_async(n: TSNode, s: bytes) -> str | None:
    return (
        "async"
        if any(c.type == "async" for c in n.children) or b"async fn" in s
        else None
    )


def detect_rust_unsafe(n: TSNode, s: bytes) -> str | None:
    return (
        "unsafe"
        if any(c.type == "unsafe" for c in n.children) or b"unsafe fn" in s
        else None
    )


def detect_rust_generic(n: TSNode, s: bytes) -> str | None:
    return (
        "generic"
        if any(c.type == "type_parameters" for c in n.children)
        else None
    )


RUST_PATTERNS: list[Callable[[TSNode, bytes], str | None]] = [
    detect_rust_async,
    detect_rust_unsafe,
    detect_rust_generic,
]

# ---------- Kotlin detectors ----------


def detect_kotlin_suspend(n: TSNode, s: bytes) -> str | None:
    return "suspend function" if b"suspend " in s[:64] else None


def detect_kotlin_data_class(n: TSNode, s: bytes) -> str | None:
    return "data class" if b"data class" in s[:80] else None


def detect_kotlin_sealed(n: TSNode, s: bytes) -> str | None:
    return "sealed class" if b"sealed class" in s[:80] else None


KOTLIN_PATTERNS: list[Callable[[TSNode, bytes], str | None]] = [
    detect_kotlin_suspend,
    detect_kotlin_data_class,
    detect_kotlin_sealed,
]


PATTERN_DETECTORS.update({
    "go": GO_PATTERNS,
    "rust": RUST_PATTERNS,
    "kotlin": KOTLIN_PATTERNS,
})
