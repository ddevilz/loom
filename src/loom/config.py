from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    env_path = Path.cwd() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# SQLite database path
LOOM_DB_PATH: str = os.getenv(
    "LOOM_DB_PATH", str(Path.home() / ".loom" / "loom.db")
)

# Optional: LLM for summary generation
LOOM_LLM_MODEL: str | None = os.getenv("LOOM_LLM_MODEL") or None
LOOM_LLM_API_KEY: str = os.getenv("LOOM_LLM_API_KEY", "")

# Logging
LOOM_LOG_LEVEL: str = os.getenv("LOOM_LOG_LEVEL", "INFO")

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
