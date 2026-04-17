from __future__ import annotations

from loom.analysis.code.calls.java import trace_calls_for_java_file
from loom.analysis.code.calls.python import (
    _build_symbol_map,
    trace_calls,
    trace_calls_for_file,
    trace_calls_for_file_with_global_symbols,
)
from loom.analysis.code.calls.typescript import trace_calls_for_ts_file

__all__ = [
    "_build_symbol_map",
    "trace_calls",
    "trace_calls_for_file",
    "trace_calls_for_file_with_global_symbols",
    "trace_calls_for_ts_file",
    "trace_calls_for_java_file",
]
