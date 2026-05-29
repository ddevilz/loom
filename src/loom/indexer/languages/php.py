"""php.py — structural parser for PHP source files using tree-sitter."""

from __future__ import annotations

from pathlib import Path

import tree_sitter_php as _ts_php
from tree_sitter import Language as _Language
from tree_sitter import Node as TSNode
from tree_sitter import Parser

from loom.graph.models import Node, NodeKind
from loom.indexer.languages._base import BaseLanguageHandler, _default_repo_name
from loom.indexer.languages._ts_utils import node_text as _node_text

_PHP_LANGUAGE = _Language(_ts_php.language_php())


class PhpHandler(BaseLanguageHandler):
    """Handler for PHP source files."""

    @property
    def language_name(self) -> str:
        return "php"

    def parse(self, source: bytes, rel_path: str) -> list[Node]:
        parser = Parser(_PHP_LANGUAGE)
        tree = parser.parse(source)
        out: list[Node] = []
        self._walk(tree.root_node, source, rel_path, out, parent_id=None)
        return out

    def _walk(
        self,
        node: TSNode,
        src: bytes,
        path: str,
        out: list[Node],
        parent_id: str | None,
    ) -> None:
        for child in node.children:
            t = child.type
            if t == "class_declaration":
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    continue
                name = _node_text(src, name_node)
                n_obj = self._build_node(
                    child, src, path,
                    kind=NodeKind.CLASS, name=name, symbol=name,
                    parent_id=parent_id,
                )
                out.append(n_obj)
                self._walk(child, src, path, out, n_obj.id)
            elif t == "interface_declaration":
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    continue
                name = _node_text(src, name_node)
                n_obj = self._build_node(
                    child, src, path,
                    kind=NodeKind.INTERFACE, name=name, symbol=name,
                    parent_id=parent_id,
                )
                out.append(n_obj)
                self._walk(child, src, path, out, n_obj.id)
            elif t == "trait_declaration":
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    continue
                name = _node_text(src, name_node)
                n_obj = self._build_node(
                    child, src, path,
                    kind=NodeKind.CLASS, name=name, symbol=name,
                    parent_id=parent_id,
                )
                out.append(n_obj)
                self._walk(child, src, path, out, n_obj.id)
            elif t == "method_declaration":
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    continue
                name = _node_text(src, name_node)
                out.append(
                    self._build_node(
                        child, src, path,
                        kind=NodeKind.METHOD, name=name, symbol=name,
                        parent_id=parent_id,
                    )
                )
            elif t == "function_definition":
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    continue
                name = _node_text(src, name_node)
                out.append(
                    self._build_node(
                        child, src, path,
                        kind=NodeKind.FUNCTION, name=name, symbol=name,
                        parent_id=parent_id,
                    )
                )
            else:
                self._walk(child, src, path, out, parent_id)


def parse_php(path: str, *, exclude_tests: bool = False) -> list[Node]:  # noqa: ARG001
    """Parse a PHP source file and return structural nodes."""
    p = Path(path)
    src = p.read_bytes()

    handler = PhpHandler()
    handler.repo_name = _default_repo_name()

    return handler.parse(src, path.replace("\\", "/"))
