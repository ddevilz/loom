# Contributing

Thanks for your interest in contributing to Loom.

## Development setup

### Requirements

- Python 3.12+
- uv
- Docker (for FalkorDB)

### Setup

```bash
uv sync
```

Start FalkorDB:

```bash
docker run -d -p 6379:6379 --name loom-db falkordb/falkordb
```

Run tests:

```bash
uv run pytest -q
```

## Pull requests

- Keep changes focused and incremental.
- Add or update tests for behavioral changes.
- Run the test suite before submitting.

## Reporting bugs

Please include:

- What you expected vs what happened
- Your OS and Python version
- Loom commands run (and relevant logs)
- FalkorDB version (Docker image tag)
