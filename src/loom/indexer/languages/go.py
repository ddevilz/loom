"""go.py — structural parser for Go source files using tree-sitter."""

from __future__ import annotations

from pathlib import Path

import tree_sitter_go as _ts_go
from tree_sitter import Language as _Language
from tree_sitter import Node as TSNode
from tree_sitter import Parser

from loom.graph.models import Node, NodeKind
from loom.indexer.languages._base import BaseLanguageHandler, _default_repo_name
from loom.indexer.languages._ts_utils import node_text as _node_text

_GO_LANGUAGE = _Language(_ts_go.language())


class GoHandler(BaseLanguageHandler):
    """Handler for Go source files."""

    @property
    def language_name(self) -> str:
        return "go"

    def parse(self, source: bytes, rel_path: str) -> list[Node]:
        parser = Parser(_GO_LANGUAGE)
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
            if child.type == "function_declaration":
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
            elif child.type == "method_declaration":
                name_node = child.child_by_field_name("name")
                if name_node is None:
                    continue
                name = _node_text(src, name_node)
                # Include receiver type to avoid symbol collision.
                # The receiver is a parameter_list containing a parameter_declaration
                # whose children include type_identifier or pointer_type.
                receiver_type = ""
                receiver_node = child.child_by_field_name("receiver")
                if receiver_node:
                    for rc in receiver_node.children:
                        if rc.type != "parameter_declaration":
                            continue
                        for rcc in rc.children:
                            if rcc.type == "type_identifier":
                                receiver_type = _node_text(src, rcc)
                                break
                            if rcc.type == "pointer_type":
                                inner = rcc.child_by_field_name("type") or rcc
                                receiver_type = _node_text(src, inner).lstrip("*")
                                break
                        if receiver_type:
                            break
                symbol = f"{receiver_type}.{name}" if receiver_type else name
                out.append(
                    self._build_node(
                        child, src, path,
                        kind=NodeKind.METHOD, name=name, symbol=symbol,
                        parent_id=parent_id,
                    )
                )
            elif child.type == "type_declaration":
                for ts in child.children:
                    if ts.type != "type_spec":
                        continue
                    name_node = ts.child_by_field_name("name")
                    if name_node is None:
                        continue
                    type_node = ts.child_by_field_name("type")
                    if type_node is None or type_node.type not in (
                        "struct_type",
                        "interface_type",
                    ):
                        continue
                    name = _node_text(src, name_node)
                    kind = (
                        NodeKind.INTERFACE
                        if type_node.type == "interface_type"
                        else NodeKind.CLASS
                    )
                    out.append(
                        self._build_node(
                            ts, src, path,
                            kind=kind, name=name, symbol=name,
                            parent_id=parent_id,
                        )
                    )
            else:
                self._walk(child, src, path, out, parent_id)


def parse_go(path: str, *, exclude_tests: bool = False) -> list[Node]:  # noqa: ARG001
    """Parse a Go source file and return structural nodes."""
    p = Path(path)
    src = p.read_bytes()

    handler = GoHandler()
    handler.repo_name = _default_repo_name()

    return handler.parse(src, path.replace("\\", "/"))
