from __future__ import annotations

from typing import Literal

PYTHON_BUILTINS: frozenset[str] = frozenset(
    {
        "abs",
        "aiter",
        "all",
        "any",
        "anext",
        "ascii",
        "bin",
        "bool",
        "breakpoint",
        "bytearray",
        "bytes",
        "callable",
        "chr",
        "classmethod",
        "compile",
        "complex",
        "delattr",
        "dict",
        "dir",
        "divmod",
        "enumerate",
        "eval",
        "exec",
        "filter",
        "float",
        "format",
        "frozenset",
        "getattr",
        "globals",
        "hasattr",
        "hash",
        "help",
        "hex",
        "id",
        "input",
        "int",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "list",
        "locals",
        "map",
        "max",
        "memoryview",
        "min",
        "next",
        "object",
        "oct",
        "open",
        "ord",
        "pow",
        "print",
        "property",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "setattr",
        "slice",
        "sorted",
        "staticmethod",
        "str",
        "sum",
        "super",
        "tuple",
        "type",
        "vars",
        "zip",
        "__import__",
    }
)

COMMON_STDLIB: frozenset[str] = frozenset(
    {
        "append",
        "extend",
        "insert",
        "remove",
        "pop",
        "clear",
        "index",
        "count",
        "sort",
        "reverse",
        "copy",
        "get",
        "keys",
        "values",
        "items",
        "update",
        "setdefault",
        "popitem",
        "add",
        "discard",
        "union",
        "intersection",
        "difference",
        "symmetric_difference",
        "issubset",
        "issuperset",
        "isdisjoint",
        "split",
        "join",
        "strip",
        "lstrip",
        "rstrip",
        "replace",
        "startswith",
        "endswith",
        "find",
        "rfind",
        "upper",
        "lower",
        "capitalize",
        "title",
        "swapcase",
        "encode",
        "decode",
        "format",
        "format_map",
        "ljust",
        "rjust",
        "center",
        "zfill",
        "expandtabs",
        "isalnum",
        "isalpha",
        "isascii",
        "isdecimal",
        "isdigit",
        "isidentifier",
        "islower",
        "isnumeric",
        "isprintable",
        "isspace",
        "istitle",
        "isupper",
        "read",
        "write",
        "close",
        "flush",
        "seek",
        "tell",
        "readline",
        "readlines",
        "writelines",
    }
)

PYTHON_NOISE: frozenset[str] = PYTHON_BUILTINS | COMMON_STDLIB


# NOTE: These language lists are intentionally conservative.
# They should only include extremely common library/built-in calls that tend to
# overwhelm call graphs without adding architectural signal.

JAVA_COMMON: frozenset[str] = frozenset(
    {
        "toString",
        "hashCode",
        "equals",
        "getClass",
        "notify",
        "notifyAll",
        "wait",
        "clone",
        "finalize",
        "size",
        "isEmpty",
        "contains",
        "add",
        "remove",
        "clear",
        "put",
        "get",
        "stream",
        "map",
        "filter",
        "forEach",
        "collect",
        "of",
        "valueOf",
        "println",
        "print",
        "format",
    }
)


JS_TS_COMMON: frozenset[str] = frozenset(
    {
        # arrays
        "push",
        "pop",
        "shift",
        "unshift",
        "slice",
        "splice",
        "map",
        "filter",
        "reduce",
        "forEach",
        "find",
        "some",
        "every",
        "includes",
        "indexOf",
        "join",
        # promises
        "then",
        "catch",
        "finally",
        # object utilities
        "keys",
        "values",
        "entries",
        "assign",
        # json
        "parse",
        "stringify",
        # logging
        "log",
        "warn",
        "error",
        "debug",
    }
)


LanguageName = Literal["python", "java", "javascript", "typescript"]


def should_ignore_call(name: str, *, language: LanguageName | None = None) -> bool:
    if language is None or language == "python":
        return name in PYTHON_NOISE

    if language == "java":
        return name in JAVA_COMMON

    if language in {"javascript", "typescript"}:
        return name in JS_TS_COMMON

    return False
