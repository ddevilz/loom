from __future__ import annotations

from loom.ingest.code.languages.constants import EXT_JS, EXT_JSX
from loom.ingest.code.registry import get_registry


def test_js_jsx_have_call_tracer() -> None:
    reg = get_registry()
    js_handler = reg.get_handler(EXT_JS)
    jsx_handler = reg.get_handler(EXT_JSX)
    assert js_handler is not None and js_handler.call_tracer is not None, (
        "EXT_JS missing call_tracer"
    )
    assert jsx_handler is not None and jsx_handler.call_tracer is not None, (
        "EXT_JSX missing call_tracer"
    )
