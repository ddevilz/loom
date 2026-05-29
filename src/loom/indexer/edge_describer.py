from __future__ import annotations

import re

GENERIC_VERBS = frozenset({
    "run", "do", "process", "execute", "call", "invoke", "main",
    "init", "setup", "handle",
})

VERB_MAP: dict[str, str] = {
    "get": "{obj} retrieval", "fetch": "{obj} retrieval",
    "set": "{obj} update", "update": "{obj} update",
    "create": "{obj} creation", "build": "{obj} building",
    "delete": "{obj} deletion", "remove": "{obj} removal",
    "validate": "{obj} validation", "check": "{obj} checking",
    "parse": "{obj} parsing", "serialize": "{obj} serialization",
    "send": "{obj} sending", "receive": "{obj} receiving",
    "save": "{obj} persistence", "load": "{obj} loading",
    "hash": "{obj} hashing", "encrypt": "{obj} encryption",
    "auth": "{obj} authentication",
}

_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _split_name(name: str) -> list[str]:
    """Split snake_case or camelCase identifier into lowercase parts."""
    if "_" in name:
        return [p.lower() for p in name.split("_") if p]
    parts = _CAMEL_RE.split(name)
    return [p.lower() for p in parts if p]


def extract_verb(name: str) -> str | None:
    parts = _split_name(name)
    if not parts:
        return None
    verb = parts[0]
    if verb in GENERIC_VERBS:
        return None
    obj = " ".join(parts[1:]) if len(parts) > 1 else ""
    template = VERB_MAP.get(verb)
    if template:
        return template.format(obj=obj).strip() if obj else verb
    return " ".join(parts)


def describe_call_edge(
    caller_name: str,
    callee_name: str,
    callee_module: str | None = None,
    caller_module: str | None = None,
) -> str | None:
    callee_verb = extract_verb(callee_name)
    if not callee_verb:
        return None
    caller_verb = extract_verb(caller_name)
    if callee_module and callee_module != caller_module:
        if caller_verb:
            return f"{caller_verb} reaches into {callee_module} for {callee_verb}"
        return f"reaches into {callee_module} for {callee_verb}"
    if caller_verb:
        return f"{caller_verb} via {callee_verb}"
    return callee_verb


def _module_from_path(path: str | None) -> str | None:
    if not path:
        return None
    parts = path.replace("\\", "/").split("/")
    return parts[-2] if len(parts) >= 2 else None


def describe_edges(edges: list, nodes_by_id: dict, *, confidence_floor: float = 0.6) -> int:
    """Mutate edges in-place — populate `description` field for eligible CALLS edges.

    Returns count of edges described.
    """
    count = 0
    for e in edges:
        kind_str = str(e.kind)
        if "CALLS" not in kind_str:
            continue
        if getattr(e, "description", None):
            continue
        if e.confidence < confidence_floor:
            continue
        if e.metadata and e.metadata.get("ambiguous"):
            continue
        caller = nodes_by_id.get(e.from_id)
        callee = nodes_by_id.get(e.to_id)
        if not caller or not callee:
            continue
        callee_mod = _module_from_path(callee.path)
        caller_mod = _module_from_path(caller.path)
        desc = describe_call_edge(
            caller.name, callee.name,
            callee_module=callee_mod, caller_module=caller_mod,
        )
        if desc:
            e.description = desc
            count += 1
    return count
