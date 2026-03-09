from __future__ import annotations

import os
from pathlib import Path

# Load .env file if present
try:
    from dotenv import load_dotenv

    env_path = Path.cwd() / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# Database configuration
LOOM_DB_HOST = os.getenv("LOOM_DB_HOST", "localhost")
LOOM_DB_PORT = int(os.getenv("LOOM_DB_PORT", "6379"))
LOOM_DB_URL = os.getenv("LOOM_DB_URL", f"redis://{LOOM_DB_HOST}:{LOOM_DB_PORT}")

# LLM configuration (optional - only needed for LLM-assisted semantic linking)
LOOM_LLM_MODEL = os.getenv("LOOM_LLM_MODEL") or None
LOOM_LLM_API_KEY = os.getenv("LOOM_LLM_API_KEY", "")
LOOM_LLM_BASE_URL = os.getenv("LOOM_LLM_BASE_URL", "")

# Embedding configuration
LOOM_EMBED_MODEL = os.getenv("LOOM_EMBED_MODEL", "nomic-ai/nomic-embed-text-v1.5")
LOOM_EMBED_DIM = int(os.getenv("LOOM_EMBED_DIM", "768"))
LOOM_EMBED_BATCH_SIZE = int(os.getenv("LOOM_EMBED_BATCH_SIZE", "32"))
LOOM_EMBED_CACHE_DIR = os.getenv(
    "LOOM_EMBED_CACHE_DIR", str(Path.home() / ".loom" / "fastembed_cache")
)

# Jira configuration
LOOM_JIRA_URL = os.getenv("LOOM_JIRA_URL", "")
LOOM_JIRA_EMAIL = os.getenv("LOOM_JIRA_EMAIL", "")
LOOM_JIRA_API_TOKEN = os.getenv("LOOM_JIRA_API_TOKEN", "")


def validate_jira_config() -> None:
    """Validate Jira configuration is complete.

    Raises:
        ValueError: If any required Jira configuration is missing.
    """
    missing = []
    if not LOOM_JIRA_URL:
        missing.append("LOOM_JIRA_URL")
    if not LOOM_JIRA_EMAIL:
        missing.append("LOOM_JIRA_EMAIL")
    if not LOOM_JIRA_API_TOKEN:
        missing.append("LOOM_JIRA_API_TOKEN")

    if missing:
        raise ValueError(
            f"Jira integration requires the following environment variables: {', '.join(missing)}. "
            "Please set them in your .env file or environment."
        )


# Default skip directories
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
