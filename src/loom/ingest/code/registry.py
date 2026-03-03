from __future__ import annotations

from typing import Protocol

from loom.core import Node
from loom.config import DEFAULT_SKIP_DIRS

from loom.ingest.code.languages.constants import (
    EXT_CSS,
    EXT_CXML,
    EXT_GO,
    EXT_HTM,
    EXT_HTML,
    EXT_JAVA,
    EXT_JS,
    EXT_JSX,
    EXT_JSON,
    EXT_PY,
    EXT_PYW,
    EXT_RB,
    EXT_RS,
    EXT_TS,
    EXT_TSX,
    EXT_XML,
    EXT_YAML,
    EXT_YML,
)


class LanguageParser(Protocol):
    def __call__(self, path: str, *, exclude_tests: bool = False) -> list[Node]: ...

# ── known non-code extensions we always skip ────────────────────────
# Note: HTML, XML, JSON, CSS, YAML are now parsed as FILE nodes
SKIP_EXTENSIONS: frozenset[str] = frozenset({
    ".scss", ".sass", ".less",  # CSS preprocessors (not yet supported)
    ".xsl", ".xslt", ".xsd", ".dtd",  # XML schemas/transforms
    ".svg", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",  # images
    ".woff", ".woff2", ".ttf", ".eot", ".otf",  # fonts
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",  # office docs
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",  # archives
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",  # media
    ".pyc", ".pyo", ".so", ".dll", ".dylib", ".o", ".a",  # compiled
    ".lock", ".map",  # build artifacts
    ".min.js", ".min.css",  # minified (parse source instead)
    ".env", ".env.local", ".env.production",  # secrets
})


class LanguageRegistry:
    """Maps file extensions → parser functions.

    Only files whose extension is registered will be parsed.
    Everything else is silently skipped — no errors on .html, .xml, etc.
    """

    def __init__(self) -> None:
        self._parsers: dict[str, LanguageParser] = {}

    def register(self, extension: str, parser: LanguageParser) -> None:
        self._parsers[extension.lower()] = parser

    def get_parser(self, extension: str) -> LanguageParser | None:
        return self._parsers.get(extension.lower())

    @property
    def supported_extensions(self) -> frozenset[str]:
        return frozenset(self._parsers.keys())

    def can_parse(self, extension: str) -> bool:
        return extension.lower() in self._parsers

    def should_skip_dir(self, dirname: str) -> bool:
        if dirname.startswith("."):
            return True
        return dirname in DEFAULT_SKIP_DIRS or dirname.endswith(".egg-info")

    def should_skip_file(self, extension: str) -> bool:
        ext = extension.lower()
        if ext in SKIP_EXTENSIONS:
            return True
        if ext not in self._parsers:
            return True
        return False


# ── singleton ───────────────────────────────────────────────────────
_registry: LanguageRegistry | None = None


def get_registry() -> LanguageRegistry:
    global _registry
    if _registry is None:
        _registry = LanguageRegistry()
        _register_defaults(_registry)
    return _registry


def _register_defaults(reg: LanguageRegistry) -> None:
    from loom.ingest.code.languages.python import parse_python
    from loom.ingest.code.languages.typescript import parse_typescript
    from loom.ingest.code.languages.javascript import parse_javascript
    from loom.ingest.code.languages.go_lang import parse_go
    from loom.ingest.code.languages.java import parse_java
    from loom.ingest.code.languages.rust import parse_rust
    from loom.ingest.code.languages.ruby import parse_ruby
    from loom.ingest.code.languages.markup import (
        parse_css,
        parse_html,
        parse_json,
        parse_xml,
        parse_yaml,
    )

    # Code languages
    reg.register(EXT_PY, parse_python)
    reg.register(EXT_PYW, parse_python)
    reg.register(EXT_TS, parse_typescript)
    reg.register(EXT_TSX, parse_typescript)
    reg.register(EXT_JS, parse_javascript)
    reg.register(EXT_JSX, parse_javascript)
    reg.register(EXT_GO, parse_go)
    reg.register(EXT_JAVA, parse_java)
    reg.register(EXT_RS, parse_rust)
    reg.register(EXT_RB, parse_ruby)

    # Markup & config files (parsed as FILE nodes with metadata)
    reg.register(EXT_HTML, parse_html)
    reg.register(EXT_HTM, parse_html)
    reg.register(EXT_XML, parse_xml)
    reg.register(EXT_CXML, parse_xml)
    reg.register(EXT_JSON, parse_json)
    reg.register(EXT_CSS, parse_css)
    reg.register(EXT_YAML, parse_yaml)
    reg.register(EXT_YML, parse_yaml)
