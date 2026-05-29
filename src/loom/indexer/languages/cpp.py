"""cpp.py — structural parser for C++ source files using tree-sitter."""

from __future__ import annotations

from pathlib import Path

import tree_sitter_cpp as _ts_cpp
from tree_sitter import Language as _Language
from tree_sitter import Node as TSNode
from tree_sitter import Parser

from loom.graph.models import Node, NodeKind
from loom.indexer.languages._base import BaseLanguageHandler, _default_repo_name
from loom.indexer.languages._ts_utils import node_text as _node_text

_CPP_LANGUAGE = _Language(_ts_cpp.language())


class CppHandler(BaseLanguageHandler):
    """Handler for C++ source files."""

    @property
    def language_name(self) -> str:
        return "cpp"

    def parse(self, source: bytes, rel_path: str) -> list[Node]:
        parser = Parser(_CPP_LANGUAGE)
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
            if t in ("class_specifier", "struct_specifier"):
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
                self._walk(child, src, path, out, n_obj.id, inside_class=True)
            elif t == "function_definition":
                decl = child.child_by_field_name("declarator")
                name = self._extract_func_name(decl, src) if decl else None
                if not name:
                    continue
                kind = NodeKind.METHOD if (inside_class or "::" in name) else NodeKind.FUNCTION
                bare = name.split("::")[-1]
                out.append(
                    self._build_node(
                        child, src, path, kind=kind, name=bare, symbol=name, parent_id=parent_id
                    )
                )
            else:
                self._walk(child, src, path, out, parent_id, inside_class)

    @staticmethod
    def _extract_func_name(decl: TSNode, src: bytes) -> str | None:
        cur: TSNode | None = decl
        while cur is not None:
            if cur.type == "function_declarator":
                inner = cur.child_by_field_name("declarator")
                if inner is None:
                    return None
                return _node_text(src, inner)
            cur = cur.child_by_field_name("declarator")
        return None


def parse_cpp(path: str, *, exclude_tests: bool = False) -> list[Node]:  # noqa: ARG001
    """Parse a C++ source file and return structural nodes."""
    p = Path(path)
    src = p.read_bytes()

    handler = CppHandler()
    handler.repo_name = _default_repo_name()

    return handler.parse(src, path.replace("\\", "/"))
