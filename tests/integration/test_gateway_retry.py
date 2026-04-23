"""Tests for FalkorDB gateway retry-with-backoff behavior.

These tests mock FalkorDB so no live connection is required, but they live in
integration/ because they exercise connection-level gateway behavior.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from loom.core.falkor.gateway import _connect_with_retry


def test_connect_with_retry_succeeds_on_third_attempt() -> None:
    """Should retry and succeed when the first two attempts fail."""
    call_count = 0
    fake_instance = MagicMock()

    def fake_falkordb(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionRefusedError("simulated failure")
        return fake_instance

    with patch("loom.core.falkor.gateway.FalkorDB", side_effect=fake_falkordb):
        with patch("loom.core.falkor.gateway.time") as mock_time:
            result = _connect_with_retry()

    assert call_count == 3
    assert result is fake_instance
    # sleep was called twice (after attempt 1 and 2)
    assert mock_time.sleep.call_count == 2


def test_connect_with_retry_raises_after_all_attempts_fail() -> None:
    """ConnectionError is raised when every retry attempt fails."""

    def always_fail(**kwargs):
        raise ConnectionRefusedError("always fails")

    with patch("loom.core.falkor.gateway.FalkorDB", side_effect=always_fail):
        with patch("loom.core.falkor.gateway.time"):
            with pytest.raises(ConnectionError, match="FalkorDB connection failed"):
                _connect_with_retry()


def test_connect_with_retry_succeeds_on_first_attempt() -> None:
    """No retries if first attempt succeeds — sleep is never called."""
    fake_instance = MagicMock()

    with patch("loom.core.falkor.gateway.FalkorDB", return_value=fake_instance):
        with patch("loom.core.falkor.gateway.time") as mock_time:
            result = _connect_with_retry()

    assert result is fake_instance
    mock_time.sleep.assert_not_called()
