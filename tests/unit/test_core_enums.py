# tests/unit/test_core_enums.py
from __future__ import annotations


def test_summary_source_values_are_all_caps() -> None:
    from loom.graph.models import SummarySource

    assert SummarySource.AGENT == "AGENT"
    assert SummarySource.AUTO == "AUTO"


def test_question_type_values_are_all_caps() -> None:
    from loom.graph.models import QuestionType

    assert QuestionType.DEAD_CODE == "DEAD_CODE"
    assert QuestionType.BRIDGE_NODE == "BRIDGE_NODE"
    assert QuestionType.MISSING_SUMMARY == "MISSING_SUMMARY"
    assert QuestionType.LOW_COHESION == "LOW_COHESION"


def test_summary_source_is_str() -> None:
    from loom.graph.models import SummarySource

    assert isinstance(SummarySource.AGENT, str)


def test_question_type_is_str() -> None:
    from loom.graph.models import QuestionType

    assert isinstance(QuestionType.DEAD_CODE, str)
