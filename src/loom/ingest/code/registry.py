from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from loom.config import DEFAULT_SKIP_DIRS
from loom.core import Edge, Node
from loom.ingest.code.languages.constants import (
    EXT_CSS,
    EXT_CXML,
    EXT_ENV,
    EXT_GO,
    EXT_HTM,
    EXT_HTML,
    EXT_INI,
    EXT_JAVA,
    EXT_JS,
    EXT_JSON,
    EXT_JSX,
    EXT_PROPERTIES,
    EXT_PY,
    EXT_PYW,
    EXT_RB,
    EXT_RS,
    EXT_TOML,
    EXT_TS,
    EXT_TSX,
    EXT_XML,
    EXT_YAML,
    EXT_YML,
)


class LanguageParser(Protocol):
    def __call__(self, path: str, *, exclude_tests: bool = False) -> list[Node]: ...


class CallTracer(Protocol):
    def __call__(self, path: str, nodes: list[Node]) -> list[Edge]: ...


@dataclass(frozen=True)
class LanguageHandler:
    language: str
    parser: LanguageParser
    call_tracer: CallTracer | None = None
    call_tracer_error_message: str | None = None


# ── known non-code extensions we always skip ────────────────────────
# Note: HTML, XML, JSON, CSS, YAML are now parsed as FILE nodes
SKIP_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".scss",
        ".sass",
        ".less",  # CSS preprocessors (not yet supported)
        ".xsl",
        ".xslt",
        ".xsd",
        ".dtd",  # XML schemas/transforms
        ".svg",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".webp",  # images
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",  # fonts
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",  # office docs
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".7z",
        ".rar",  # archives
        ".mp3",
        ".mp4",
        ".wav",
        ".avi",
        ".mov",
        ".mkv",  # media
        ".pyc",
        ".pyo",
        ".so",
        ".dll",
        ".dylib",
        ".o",
        ".a",  # compiled
        ".lock",
        ".map",  # build artifacts
    }
)


class LanguageRegistry:
    """Maps file extensions → parser functions.

    Only files whose extension is registered will be parsed.
    Everything else is silently skipped — no errors on .html, .xml, etc.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, LanguageHandler] = {}

    def register(
        self,
        extension: str,
        language: str,
        parser: LanguageParser,
        *,
        call_tracer: CallTracer | None = None,
        call_tracer_error_message: str | None = None,
    ) -> None:
        self._handlers[extension.lower()] = LanguageHandler(
            language=language,
            parser=parser,
            call_tracer=call_tracer,
            call_tracer_error_message=call_tracer_error_message,
        )

    def get_handler(self, extension: str) -> LanguageHandler | None:
        return self._handlers.get(extension.lower())

    def get_extension_for_path(self, path: str) -> str:
        p = Path(path)
        if p.name == ".env" or p.name.startswith(".env."):
            return EXT_ENV
        return p.suffix.lower()

    def get_handler_for_path(self, path: str) -> LanguageHandler | None:
        return self.get_handler(self.get_extension_for_path(path))

    def get_language(self, extension: str) -> str | None:
        handler = self.get_handler(extension)
        return handler.language if handler is not None else None

    def get_language_for_path(self, path: str) -> str | None:
        return self.get_language(self.get_extension_for_path(path))

    def get_parser(self, extension: str) -> LanguageParser | None:
        handler = self.get_handler(extension)
        return handler.parser if handler is not None else None

    @property
    def supported_extensions(self) -> frozenset[str]:
        return frozenset(self._handlers.keys())

    def can_parse(self, extension: str) -> bool:
        return extension.lower() in self._handlers

    def should_skip_dir(self, dirname: str) -> bool:
        if dirname.startswith("."):
            return True
        return dirname in DEFAULT_SKIP_DIRS or dirname.endswith(".egg-info")

    def should_skip_file(self, extension: str, filename: str = "") -> bool:
        ext = extension.lower()
        if ext in SKIP_EXTENSIONS:
            return True
        if filename.endswith((".min.js", ".min.css")):
            return True
        if ext not in self._handlers:
            return True
        return False

    def should_skip_path(self, path: str) -> bool:
        p = Path(path)
        ext = self.get_extension_for_path(path)
        return self.should_skip_file(ext, filename=p.name)


# ── singleton ───────────────────────────────────────────────────────
_registry: LanguageRegistry | None = None
_registry_lock = threading.Lock()


def get_registry() -> LanguageRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = LanguageRegistry()
                _register_defaults(_registry)
    return _registry


def _register_defaults(reg: LanguageRegistry) -> None:
    from loom.analysis.code.calls import trace_calls_for_file
    from loom.analysis.code.calls_java import trace_calls_for_java_file
    from loom.analysis.code.calls_ts import trace_calls_for_ts_file
    from loom.ingest.code.languages.go_lang import parse_go
    from loom.ingest.code.languages.java import parse_java
    from loom.ingest.code.languages.javascript import parse_javascript
    from loom.ingest.code.languages.markup import (
        parse_css,
        parse_env,
        parse_html,
        parse_ini,
        parse_json,
        parse_properties,
        parse_toml,
        parse_xml,
        parse_yaml,
    )
    from loom.ingest.code.languages.python import parse_python
    from loom.ingest.code.languages.ruby import parse_ruby
    from loom.ingest.code.languages.rust import parse_rust
    from loom.ingest.code.languages.typescript import parse_typescript

    # Code languages
    reg.register(
        EXT_PY,
        "python",
        parse_python,
        call_tracer=trace_calls_for_file,
        call_tracer_error_message="python call tracing failed",
    )
    reg.register(
        EXT_PYW,
        "python",
        parse_python,
        call_tracer=trace_calls_for_file,
        call_tracer_error_message="python call tracing failed",
    )
    reg.register(
        EXT_TS,
        "typescript",
        parse_typescript,
        call_tracer=trace_calls_for_ts_file,
        call_tracer_error_message="typescript call tracing failed",
    )
    reg.register(
        EXT_TSX,
        "tsx",
        parse_typescript,
        call_tracer=trace_calls_for_ts_file,
        call_tracer_error_message="typescript call tracing failed",
    )
    reg.register(
        EXT_JS,
        "javascript",
        parse_javascript,
    )
    reg.register(
        EXT_JSX,
        "javascript",
        parse_javascript,
    )
    reg.register(EXT_GO, "go", parse_go)
    reg.register(
        EXT_JAVA,
        "java",
        parse_java,
        call_tracer=trace_calls_for_java_file,
        call_tracer_error_message="java call tracing failed",
    )
    reg.register(EXT_RS, "rust", parse_rust)
    reg.register(EXT_RB, "ruby", parse_ruby)

    # Markup & config files (parsed as FILE nodes with metadata)
    reg.register(EXT_HTML, "html", parse_html)
    reg.register(EXT_HTM, "html", parse_html)
    reg.register(EXT_XML, "xml", parse_xml)
    reg.register(EXT_CXML, "xml", parse_xml)
    reg.register(EXT_JSON, "json", parse_json)
    reg.register(EXT_CSS, "css", parse_css)
    reg.register(EXT_YAML, "yaml", parse_yaml)
    reg.register(EXT_YML, "yaml", parse_yaml)

    reg.register(EXT_PROPERTIES, "properties", parse_properties)
    reg.register(EXT_TOML, "toml", parse_toml)
    reg.register(EXT_INI, "ini", parse_ini)
    reg.register(EXT_ENV, "env", parse_env)
