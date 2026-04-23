from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import loom.cli
from loom.core.context import DB

runner = CliRunner()


def test_cli_help_shows_analyze_command() -> None:
    result = runner.invoke(loom.cli.app, ["--help"])
    assert result.exit_code == 0
    assert "analyze" in result.stdout


def test_cli_analyze_calls_index_repo(monkeypatch, tmp_path: Path) -> None:
    from loom.ingest.pipeline import IndexResult

    fake_result = IndexResult(
        repo_path=tmp_path,
        files_parsed=5,
        files_skipped=1,
        nodes_written=20,
        edges_written=10,
    )

    async def fake_index_repo(path, db, **kw):
        return fake_result

    monkeypatch.setattr("loom.cli.ingest.index_repo", fake_index_repo)

    result = runner.invoke(
        loom.cli.app,
        ["analyze", str(tmp_path)],
        obj={"db": DB(path=":memory:")},
    )

    assert result.exit_code == 0
    assert "5" in result.stdout  # files_parsed


def test_cli_analyze_uses_db_flag(monkeypatch, tmp_path: Path) -> None:
    from loom.ingest.pipeline import IndexResult

    db_paths: list = []

    async def fake_index_repo(path, db, **kw):
        db_paths.append(db.path)
        return IndexResult(
            repo_path=tmp_path,
            files_parsed=0,
            files_skipped=0,
            nodes_written=0,
            edges_written=0,
        )

    monkeypatch.setattr("loom.cli.ingest.index_repo", fake_index_repo)

    custom_db = tmp_path / "custom.db"
    result = runner.invoke(
        loom.cli.app,
        ["--db", str(custom_db), "analyze", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert len(db_paths) == 1
    assert Path(db_paths[0]) == custom_db


def test_cli_analyze_shows_errors(monkeypatch, tmp_path: Path) -> None:
    from loom.ingest.pipeline import IndexResult

    async def fake_index_repo(path, db, **kw):
        return IndexResult(
            repo_path=tmp_path,
            files_parsed=1,
            files_skipped=0,
            nodes_written=1,
            edges_written=0,
            errors=["parse failed src/a.py: SyntaxError"],
        )

    monkeypatch.setattr("loom.cli.ingest.index_repo", fake_index_repo)

    result = runner.invoke(
        loom.cli.app,
        ["analyze", str(tmp_path)],
        obj={"db": DB(path=":memory:")},
    )

    assert result.exit_code == 0
    assert "warn" in result.stdout or "parse failed" in result.stdout
