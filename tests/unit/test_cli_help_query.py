from __future__ import annotations

from typer.testing import CliRunner

import loom.cli

runner = CliRunner()


def test_cli_help_shows_query_command() -> None:
    result = runner.invoke(loom.cli.app, ["--help"])
    assert result.exit_code == 0
    assert "query" in result.stdout
    assert "analyze" in result.stdout
