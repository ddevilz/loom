from __future__ import annotations

from loom.core.falkor import gateway


def test_falkordb_connect_kwargs_uses_db_url_host_and_port(monkeypatch) -> None:
    monkeypatch.setattr(gateway, "LOOM_DB_URL", "redis://db.example.com:6380")
    monkeypatch.setattr(gateway, "LOOM_DB_HOST", "localhost")
    monkeypatch.setattr(gateway, "LOOM_DB_PORT", 6379)

    assert gateway._falkordb_connect_kwargs() == {
        "host": "db.example.com",
        "port": 6380,
    }


def test_falkordb_connect_kwargs_falls_back_when_url_has_no_hostname(
    monkeypatch,
) -> None:
    monkeypatch.setattr(gateway, "LOOM_DB_URL", "not-a-url")
    monkeypatch.setattr(gateway, "LOOM_DB_HOST", "localhost")
    monkeypatch.setattr(gateway, "LOOM_DB_PORT", 6379)

    assert gateway._falkordb_connect_kwargs() == {
        "host": "localhost",
        "port": 6379,
    }
