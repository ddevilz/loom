"""rust.py — structural parser for Rust source files using tree-sitter."""

from __future__ import annotations

from pathlib import Path

import tree_sitter_rust as _ts_rust
from tree_sitter import Language as _Language
from tree_sitter import Node as TSNode
from tree_sitter import Parser

from loom.graph.models import Node, NodeKind
from loom.indexer.languages._base import BaseLanguageHandler, _default_repo_name
from loom.indexer.languages._ts_utils import node_text as _node_text

_RUST_LANGUAGE = _Language(_ts_rust.language())


class RustHandler(BaseLanguageHandler):
    """Handler for Rust source files."""

    @property
    def language_name(self) -> str:
        return "rust"

    def parse(self, source: bytes, rel_path: str) -> list[Node]:
        parser = Parser(_RUST_LANGUAGE)
        tree = parser.parse(source)
        out: list[Node] = []
        self._walk(tree.root_node, source, rel_path, out, parent_id=None, inside_impl=False)
        return out

    def _walk(
        self,
        node: TSNode,
        src: bytes,
        path: str,
        out: list[Node],
        parent_id: str | None,
        inside_impl: bool,
    ) -> None:
        for child in node.children:
            t = child.type
            if t == "function_item":
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    continue
                name = _node_text(src, name_node)
                kind = NodeKind.METHOD if inside_impl else NodeKind.FUNCTION
                out.append(
                    self._build_node(
                        child, src, path, kind=kind, name=name, symbol=name, parent_id=parent_id
                    )
                )
            elif t in ("struct_item", "enum_item"):
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
                self._walk(child, src, path, out, n_obj.id, inside_impl)
            elif t == "trait_item":
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
                self._walk(child, src, path, out, n_obj.id, inside_impl)
            elif t == "impl_item":
                self._walk(child, src, path, out, parent_id, inside_impl=True)
            else:
                self._walk(child, src, path, out, parent_id, inside_impl)


def parse_rust(path: str, *, exclude_tests: bool = False) -> list[Node]:  # noqa: ARG001
    """Parse a Rust source file and return structural nodes."""
    p = Path(path)
    src = p.read_bytes()

    handler = RustHandler()
    handler.repo_name = _default_repo_name()

    return handler.parse(src, path.replace("\\", "/"))
