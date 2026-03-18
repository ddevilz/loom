from __future__ import annotations

import re


def tokenize_text(text: str) -> set[str]:
    """Tokenize arbitrary text into a set of lowercase word tokens.

    Splits on non-alphanumeric boundaries and handles camelCase/PascalCase.
    """
    tokens: set[str] = set()
    for word in re.findall(r"[a-zA-Z][a-zA-Z0-9_]*", text):
        camel = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", word)
        tokens.update(t.lower() for t in camel.split() if t)
    return tokens
