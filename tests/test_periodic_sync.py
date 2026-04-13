"""Tests for the periodic background sync loop in server/app.py."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_periodic_sync_loop_calls_bulk_sync():
    """_periodic_sync_loop should call bulk_sync_documents after each sleep interval."""
    from server.app import _periodic_sync_loop

    call_count = 0

    async def fake_bulk_sync(force: bool):
        nonlocal call_count
        call_count += 1

    with patch("server.app.bulk_sync_documents", side_effect=fake_bulk_sync):
        # Run the loop with a tiny interval; cancel after the first real call
        task = asyncio.create_task(_periodic_sync_loop(interval_minutes=0))  # 0 min = immediate
        await asyncio.sleep(0.05)  # give the loop one iteration
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert call_count >= 1, "bulk_sync_documents should have been called at least once"


@pytest.mark.asyncio
async def test_periodic_sync_loop_logs_next_run(caplog):
    """_periodic_sync_loop should log 'Next run at HH:MM' after each sync."""
    import logging
    from server.app import _periodic_sync_loop

    async def fake_bulk_sync(force: bool):
        pass

    with patch("server.app.bulk_sync_documents", side_effect=fake_bulk_sync):
        with patch("server.app.logger") as mock_logger:
            task = asyncio.create_task(_periodic_sync_loop(interval_minutes=0))
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # At least one call should contain "Next run at"
        info_calls = [str(call) for call in mock_logger.info.call_args_list]
        assert any("Next run at" in c for c in info_calls), (
            f"Expected 'Next run at' in log output, got: {info_calls}"
        )


def test_sync_interval_minutes_default():
    """Settings should default to 15 minutes."""
    from core.config import Settings
    # Construct a fresh Settings with required fields only
    s = Settings(
        paperless_url="http://mock",
        paperless_token="tok",
        gemini_api_key="key",
    )
    assert s.sync_interval_minutes == 15


def test_sync_interval_minutes_configurable():
    """Settings should accept a custom SYNC_INTERVAL_MINUTES value."""
    from core.config import Settings
    s = Settings(
        paperless_url="http://mock",
        paperless_token="tok",
        gemini_api_key="key",
        sync_interval_minutes=60,
    )
    assert s.sync_interval_minutes == 60


def test_sync_interval_minutes_disabled():
    """SYNC_INTERVAL_MINUTES=0 disables periodic sync."""
    from core.config import Settings
    s = Settings(
        paperless_url="http://mock",
        paperless_token="tok",
        gemini_api_key="key",
        sync_interval_minutes=0,
    )
    assert s.sync_interval_minutes == 0
