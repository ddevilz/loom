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

<<<<<<< HEAD
# Optional: LLM for summary generation
LOOM_LLM_MODEL: str | None = os.getenv("LOOM_LLM_MODEL") or None
LOOM_LLM_API_KEY: str = os.getenv("LOOM_LLM_API_KEY", "")

# Logging
LOOM_LOG_LEVEL: str = os.getenv("LOOM_LOG_LEVEL", "INFO")

# Default skip directories for repo walking
=======
# LLM configuration (optional - only needed for LLM-assisted semantic linking)
LOOM_LLM_MODEL = os.getenv("LOOM_LLM_MODEL") or None
LOOM_LLM_API_KEY = os.getenv("LOOM_LLM_API_KEY", "")
LOOM_LLM_BASE_URL = os.getenv("LOOM_LLM_BASE_URL", "")

# Embedding configuration
LOOM_EMBED_ENABLED = os.getenv("LOOM_EMBED_ENABLED", "1") != "0"
LOOM_EMBED_MODEL = os.getenv("LOOM_EMBED_MODEL", "nomic-ai/nomic-embed-text-v1.5")
LOOM_EMBED_DIM = int(os.getenv("LOOM_EMBED_DIM", "768"))
LOOM_EMBED_BATCH_SIZE = int(os.getenv("LOOM_EMBED_BATCH_SIZE", "32"))
LOOM_EMBED_CACHE_DIR = os.getenv(
    "LOOM_EMBED_CACHE_DIR", str(Path.home() / ".loom" / "fastembed_cache")
)
LOOM_COMMUNITY_MIN_MODULARITY = float(os.getenv("LOOM_COMMUNITY_MIN_MODULARITY", "0.3"))


# Semantic linker thresholds
def _threshold(env_var: str, default: str) -> float:
    value = float(os.getenv(env_var, default))
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{env_var}={value!r} must be in [0.0, 1.0]")
    return value


LOOM_LINKER_EMBED_THRESHOLD = _threshold("LOOM_LINKER_EMBED_THRESHOLD", "0.85")

# Embedding backend selection
LOOM_EMBED_BACKEND: str = os.getenv("LOOM_EMBED_BACKEND", "fastembed")
if LOOM_EMBED_BACKEND not in ("infinity", "fastembed"):
    raise ValueError(
        f"LOOM_EMBED_BACKEND must be 'infinity' or 'fastembed', got {LOOM_EMBED_BACKEND!r}"
    )

LOOM_EMBED_CACHE_SIZE_GB: int = int(os.getenv("LOOM_EMBED_CACHE_SIZE_GB", "1"))

# Blast radius depth cap
LOOM_BLAST_RADIUS_MAX_DEPTH: int = int(os.getenv("LOOM_BLAST_RADIUS_MAX_DEPTH", "10"))
if not 1 <= LOOM_BLAST_RADIUS_MAX_DEPTH <= 50:
    raise ValueError(
        f"LOOM_BLAST_RADIUS_MAX_DEPTH must be 1–50, got {LOOM_BLAST_RADIUS_MAX_DEPTH}"
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
>>>>>>> main
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
