import subprocess
from pathlib import Path

import pytest

from loom.graph.db import DB
from loom.graph.repository import Repository
from loom.indexer.pipeline import index_repo


@pytest.mark.asyncio
async def test_pipeline_creates_layer_and_description_columns(tmp_path: Path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)

    src = tmp_path / "src" / "services"
    src.mkdir(parents=True)
    (src / "user_service.py").write_text(
        "def get_user(user_id):\n    return validate_id(user_id)\n\n"
        "def validate_id(user_id):\n    return user_id > 0\n"
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)

    db = DB(path=str(tmp_path / "loom.db"))
    db.connect()
    await index_repo(tmp_path, Repository(db))

    repo = Repository(db)
    nodes = repo.nodes.list_all_undeleted()
    # Service layer should be assigned
    assert any(n.layer == "service" for n in nodes), (
        f"No service layer: {[(n.path, n.layer) for n in nodes]}"
    )
    # CALLS edge description should be populated (get_user → validate_id)
    edges = repo.edges.get_all()
    calls = [e for e in edges if str(e.kind).endswith("CALLS")]
    assert any(e.description for e in calls), "No edge descriptions populated"
