from __future__ import annotations

from loom.analysis.code.noise_filter import should_ignore_call


def test_should_ignore_call_python_default_backward_compatible():
    assert should_ignore_call("print") is True
    assert should_ignore_call("len") is True
    assert should_ignore_call("callee") is False


def test_should_ignore_call_python_explicit_language():
    assert should_ignore_call("print", language="python") is True
    assert should_ignore_call("callee", language="python") is False


def test_should_ignore_call_java_noise():
    assert should_ignore_call("toString", language="java") is True
    assert should_ignore_call("hashCode", language="java") is True
    assert should_ignore_call("stream", language="java") is True
    assert should_ignore_call("businessLogic", language="java") is False


def test_should_ignore_call_ts_js_noise():
    assert should_ignore_call("map", language="typescript") is True
    assert should_ignore_call("then", language="typescript") is True
    assert should_ignore_call("log", language="javascript") is True
    assert should_ignore_call("render", language="typescript") is False
