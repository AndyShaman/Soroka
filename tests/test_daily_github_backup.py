"""Tests for the nightly GitHub backup job. Each scenario asserts that the
job either runs the lite-export + replace=True upload or short-circuits
silently when prerequisites are missing — operators should never see a
broken bot loop because of an absent token or a stuck wizard."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.main import (
    _daily_github_backup_job, BACKUP_FAILURE_DM_THRESHOLD, DAILY_BACKUP_TAG,
)
from src.core.db import open_db, init_schema
from src.core.owners import (
    create_or_get_owner, advance_setup_step, get_owner, update_owner_field,
)


def _ctx(conn, db_path, owner_id=1):
    settings = MagicMock(owner_telegram_id=owner_id, db_path=str(db_path))
    ctx = MagicMock()
    ctx.application.bot_data = {"settings": settings, "conn": conn}
    ctx.bot.send_message = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_skip_when_no_owner_yet(tmp_path):
    """Bot started but the owner row does not exist (first run). The job
    must return without touching GitHub or the export pipeline."""
    db_path = tmp_path / "x.db"
    conn = open_db(str(db_path))
    init_schema(conn)
    ctx = _ctx(conn, db_path)
    with patch("src.bot.main.GitHubMirror") as mirror_cls, \
         patch("src.bot.main.build_export") as exp:
        await _daily_github_backup_job(ctx)
    mirror_cls.assert_not_called()
    exp.assert_not_called()


@pytest.mark.asyncio
async def test_skip_when_setup_in_progress(tmp_path):
    """Owner exists but the wizard is still on an early step. We must not
    upload partial state to GitHub."""
    db_path = tmp_path / "x.db"
    conn = open_db(str(db_path))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    advance_setup_step(conn, 1, "jina")
    ctx = _ctx(conn, db_path)
    with patch("src.bot.main.GitHubMirror") as mirror_cls, \
         patch("src.bot.main.build_export") as exp:
        await _daily_github_backup_job(ctx)
    mirror_cls.assert_not_called()
    exp.assert_not_called()


@pytest.mark.asyncio
async def test_skip_when_no_github_credentials(tmp_path):
    """Wizard is done but the user skipped GitHub. Job is a no-op."""
    db_path = tmp_path / "x.db"
    conn = open_db(str(db_path))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    advance_setup_step(conn, 1, "done")
    ctx = _ctx(conn, db_path)
    with patch("src.bot.main.GitHubMirror") as mirror_cls, \
         patch("src.bot.main.build_export") as exp:
        await _daily_github_backup_job(ctx)
    mirror_cls.assert_not_called()
    exp.assert_not_called()


@pytest.mark.asyncio
async def test_uploads_lite_archive_with_replace(tmp_path):
    """Happy path: setup done, mirror configured. Job calls build_export
    with lite=True and uploads under DAILY_BACKUP_TAG with replace=True so
    the previous day's release is overwritten."""
    db_path = tmp_path / "x.db"
    conn = open_db(str(db_path))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    advance_setup_step(conn, 1, "done")
    update_owner_field(conn, 1, "github_token", "ghp_dummy")
    update_owner_field(conn, 1, "github_mirror_repo", "me/soroka-data")
    ctx = _ctx(conn, db_path)

    with patch("src.bot.main.GitHubMirror") as mirror_cls, \
         patch("src.bot.main.build_export") as exp:
        instance = mirror_cls.return_value
        instance.upload_release = AsyncMock(
            return_value="https://example.test/release.zip",
        )
        # build_export must produce a real file on disk for the upload step
        # to find later — emulate by writing a stub at output_path.
        def _fake_export(*, db_path, attachments_dir, output_path, lite):
            assert lite is True
            assert attachments_dir is None
            Path(output_path).write_bytes(b"stub")
            return output_path
        exp.side_effect = _fake_export
        await _daily_github_backup_job(ctx)

    mirror_cls.assert_called_once_with(
        token="ghp_dummy", repo="me/soroka-data",
    )
    exp.assert_called_once()
    instance.upload_release.assert_awaited_once()
    kwargs = instance.upload_release.await_args.kwargs
    assert kwargs["tag"] == DAILY_BACKUP_TAG
    assert kwargs["replace"] is True
    saved = get_owner(conn, 1)
    assert saved.last_backup_at  # ISO/compact timestamp persisted
    assert saved.last_backup_error is None
    assert saved.backup_failure_count == 0


@pytest.mark.asyncio
async def test_mirror_error_does_not_propagate(tmp_path):
    """A GitHub-side failure (rate limit, transient 5xx) must be swallowed
    so the bot loop keeps running until the next nightly tick."""
    from src.adapters.github_mirror import GitHubMirrorError

    db_path = tmp_path / "x.db"
    conn = open_db(str(db_path))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    advance_setup_step(conn, 1, "done")
    update_owner_field(conn, 1, "github_token", "ghp_dummy")
    update_owner_field(conn, 1, "github_mirror_repo", "me/soroka-data")
    ctx = _ctx(conn, db_path)

    with patch("src.bot.main.GitHubMirror") as mirror_cls, \
         patch("src.bot.main.build_export") as exp:
        instance = mirror_cls.return_value
        instance.upload_release = AsyncMock(side_effect=GitHubMirrorError("502"))
        def _fake_export(*, db_path, attachments_dir, output_path, lite):
            Path(output_path).write_bytes(b"stub")
            return output_path
        exp.side_effect = _fake_export
        await _daily_github_backup_job(ctx)  # must not raise

    saved = get_owner(conn, 1)
    assert saved.backup_failure_count == 1
    assert saved.last_backup_error and "502" in saved.last_backup_error
    assert saved.last_backup_at is None
    ctx.bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_failure_threshold_dms_owner_and_resets_counter(tmp_path):
    """After BACKUP_FAILURE_DM_THRESHOLD consecutive failures, the job DMs
    the owner once and resets the counter so the next DM only fires after
    another full window of failures (no daily spam)."""
    from src.adapters.github_mirror import GitHubMirrorError

    db_path = tmp_path / "x.db"
    conn = open_db(str(db_path))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    advance_setup_step(conn, 1, "done")
    update_owner_field(conn, 1, "github_token", "ghp_dummy")
    update_owner_field(conn, 1, "github_mirror_repo", "me/soroka-data")
    # Simulate two prior failures — this run will be the threshold-hitting one.
    update_owner_field(conn, 1, "backup_failure_count",
                        BACKUP_FAILURE_DM_THRESHOLD - 1)
    ctx = _ctx(conn, db_path)

    with patch("src.bot.main.GitHubMirror") as mirror_cls, \
         patch("src.bot.main.build_export") as exp:
        instance = mirror_cls.return_value
        instance.upload_release = AsyncMock(
            side_effect=GitHubMirrorError("token unauthorized"),
        )
        def _fake_export(*, db_path, attachments_dir, output_path, lite):
            Path(output_path).write_bytes(b"stub")
            return output_path
        exp.side_effect = _fake_export
        await _daily_github_backup_job(ctx)

    ctx.bot.send_message.assert_awaited_once()
    sent = ctx.bot.send_message.await_args.kwargs
    assert sent["chat_id"] == 1
    assert "/setgithub" in sent["text"]
    saved = get_owner(conn, 1)
    assert saved.backup_failure_count == 0  # reset after notification
