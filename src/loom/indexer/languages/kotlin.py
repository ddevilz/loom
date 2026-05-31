"""kotlin.py — structural parser for Kotlin source files using tree-sitter."""

from __future__ import annotations

from pathlib import Path

import tree_sitter_kotlin as _ts_kotlin
from tree_sitter import Language as _Language
from tree_sitter import Node as TSNode
from tree_sitter import Parser

from loom.graph.models import Node, NodeKind
from loom.indexer.languages._base import BaseLanguageHandler, _default_repo_name
from loom.indexer.languages._ts_utils import node_text as _node_text

_KT_LANGUAGE = _Language(_ts_kotlin.language())


class KotlinHandler(BaseLanguageHandler):
    """Handler for Kotlin source files."""

    @property
    def language_name(self) -> str:
        return "kotlin"

    def parse(self, source: bytes, rel_path: str) -> list[Node]:
        parser = Parser(_KT_LANGUAGE)
        tree = parser.parse(source)
        out: list[Node] = []
        self._walk(tree.root_node, source, rel_path, out, parent_id=None, inside_class=False)
        return out

    def _walk(
        self,
        node: TSNode,
        src: bytes,
        path: str,
        out: list[Node],
        parent_id: str | None,
        inside_class: bool,
    ) -> None:
        for child in node.children:
            t = child.type
            if t == "function_declaration":
                name_node = child.child_by_field_name("name") or self._find_simple_identifier(child)
                if name_node is None:
                    continue
                name = _node_text(src, name_node)
                kind = NodeKind.METHOD if inside_class else NodeKind.FUNCTION
                out.append(
                    self._build_node(
                        child, src, path, kind=kind, name=name, symbol=name, parent_id=parent_id
                    )
                )
            elif t in ("class_declaration", "object_declaration", "companion_object"):
                name_node = child.child_by_field_name("name") or self._find_simple_identifier(child)
                if name_node is None:
                    if t == "companion_object":
                        name = "Companion"
                    else:
                        continue
                else:
                    name = _node_text(src, name_node)
                n_obj = self._build_node(
                    child,
                    src,
                    path,
                    kind=NodeKind.CLASS,
                    name=name,
                    symbol=name,
                    parent_id=parent_id,
                )
                out.append(n_obj)
                self._walk(child, src, path, out, n_obj.id, inside_class=True)
            else:
                self._walk(child, src, path, out, parent_id, inside_class)

    @staticmethod
    def _find_simple_identifier(n: TSNode) -> TSNode | None:
        for c in n.children:
            if c.type == "simple_identifier":
                return c
        return None


def parse_kotlin(path: str, *, exclude_tests: bool = False) -> list[Node]:  # noqa: ARG001
    """Parse a Kotlin source file and return structural nodes."""
    p = Path(path)
    src = p.read_bytes()

    handler = KotlinHandler()
    handler.repo_name = _default_repo_name()

    return handler.parse(src, path.replace("\\", "/"))
