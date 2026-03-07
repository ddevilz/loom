from __future__ import annotations

from pathlib import Path

from loom.analysis.code.parser import parse_code, parse_repo
from loom.core.falkor.mappers import deserialize_node_props, serialize_node_props


def test_parse_code_nodes_have_content_hash(tmp_path: Path) -> None:
    p = tmp_path / "mod.py"
    p.write_text("def f():\n    return 1\n", encoding="utf-8")

    nodes = parse_code(str(p))
    assert nodes
    for n in nodes:
        assert n.content_hash is not None
        assert isinstance(n.content_hash, str)
        assert n.content_hash


def test_content_hash_stable_for_identical_content(tmp_path: Path) -> None:
    p = tmp_path / "mod.py"
    p.write_text("def f():\n    return 1\n", encoding="utf-8")

    nodes1 = parse_code(str(p))
    nodes2 = parse_code(str(p))

    by_id_1 = {n.id: n for n in nodes1}
    by_id_2 = {n.id: n for n in nodes2}

    assert by_id_1.keys() == by_id_2.keys()
    for node_id in by_id_1:
        assert by_id_1[node_id].content_hash == by_id_2[node_id].content_hash


def test_content_hash_changes_on_whitespace_edit(tmp_path: Path) -> None:
    p = tmp_path / "mod.py"
    p.write_text("def f():\n    return 1\n", encoding="utf-8")

    nodes1 = parse_code(str(p))
    h1 = {n.id: n.content_hash for n in nodes1}

    p.write_text("def f():\n\n    return 1\n", encoding="utf-8")
    nodes2 = parse_code(str(p))
    h2 = {n.id: n.content_hash for n in nodes2}

    assert h1.keys() == h2.keys()
    assert h1 != h2


def test_content_hash_roundtrip_via_mappers() -> None:
    p = "src/auth.py"
    nodes = parse_code("tests/fixtures/sample_repo/auth.py")
    assert nodes

    n = nodes[0]
    assert n.content_hash is not None

    props = serialize_node_props(n)
    restored_props = deserialize_node_props(dict(props))

    assert restored_props.get("content_hash") == n.content_hash


def test_parse_repo_sets_content_hash_for_all_nodes() -> None:
    nodes = parse_repo("tests/fixtures/sample_repo")
    assert nodes
    for n in nodes:
        assert n.content_hash is not None
        assert n.content_hash
