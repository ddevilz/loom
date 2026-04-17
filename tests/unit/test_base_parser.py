# tests/unit/test_base_parser.py
from loom.ingest.code.languages._base import _BaseContext


def test_push_pop_class():
    ctx = _BaseContext()
    ctx.push_class("MyClass")
    assert ctx.current_class() == "MyClass"
    ctx.pop_class()
    assert ctx.current_class() is None


def test_push_pop_fn():
    ctx = _BaseContext()
    ctx.push_fn("my_fn")
    assert ctx.current_fn() == "my_fn"
    ctx.pop_fn()
    assert ctx.current_fn() is None


def test_qualified_name_class_and_fn():
    ctx = _BaseContext()
    ctx.push_class("MyClass")
    ctx.push_fn("my_method")
    assert ctx.qualified_name() == "MyClass.my_method"


def test_qualified_name_fn_only():
    ctx = _BaseContext()
    ctx.push_fn("standalone")
    assert ctx.qualified_name() == "standalone"


def test_qualified_name_empty():
    ctx = _BaseContext()
    assert ctx.qualified_name() == ""


def test_pop_on_empty_does_not_raise(caplog):
    """pop on empty stack must be a no-op with a warning, never raise."""
    import logging
    ctx = _BaseContext()
    with caplog.at_level(logging.WARNING):
        ctx.pop_class()   # empty — must not raise
        ctx.pop_fn()      # empty — must not raise
    assert len(caplog.records) == 2


def test_nested_class_and_fn():
    ctx = _BaseContext()
    ctx.push_class("Outer")
    ctx.push_class("Inner")
    assert ctx.current_class() == "Inner"
    ctx.pop_class()
    assert ctx.current_class() == "Outer"
