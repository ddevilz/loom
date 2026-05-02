from __future__ import annotations

import logging
import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    env_path = Path.cwd() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# Logging — set before any loom logger is used
LOOM_LOG_LEVEL: str = os.getenv("LOOM_LOG_LEVEL", "WARNING")
logging.basicConfig(level=getattr(logging, LOOM_LOG_LEVEL, logging.WARNING))

# Default skip directories for repo walking
DEFAULT_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        "vendor",
        "dist",
        "build",
        ".venv",
        "venv",
        ".env",
        ".tox",
        ".eggs",
        ".next",
        ".nuxt",
        "target",
    }
)
