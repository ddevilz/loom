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

# LLM configuration
LOOM_LLM_MODEL = os.getenv("LOOM_LLM_MODEL", "gpt-4o-mini")
LOOM_LLM_API_KEY = os.getenv("LOOM_LLM_API_KEY", "")
LOOM_LLM_BASE_URL = os.getenv("LOOM_LLM_BASE_URL", "")
LOOM_LOCAL_MODEL = os.getenv("LOOM_LOCAL_MODEL", "llama3.2")

# Embedding configuration
LOOM_EMBED_MODEL = os.getenv("LOOM_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
LOOM_EMBED_BATCH_SIZE = int(os.getenv("LOOM_EMBED_BATCH_SIZE", "32"))

# Jira configuration
LOOM_JIRA_URL = os.getenv("LOOM_JIRA_URL", "")
LOOM_JIRA_EMAIL = os.getenv("LOOM_JIRA_EMAIL", "")
LOOM_JIRA_API_TOKEN = os.getenv("LOOM_JIRA_API_TOKEN", "")

# Confluence configuration
LOOM_CONFLUENCE_URL = os.getenv("LOOM_CONFLUENCE_URL", "")
LOOM_CONFLUENCE_EMAIL = os.getenv("LOOM_CONFLUENCE_EMAIL", "")
LOOM_CONFLUENCE_API_TOKEN = os.getenv("LOOM_CONFLUENCE_API_TOKEN", "")

# Notion configuration
LOOM_NOTION_TOKEN = os.getenv("LOOM_NOTION_TOKEN", "")

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
