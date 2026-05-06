"""Tests for the /models setup wizard step.

The defaults dialog lets a brand-new owner accept a curated GLM+Gemma
free pair with one tap, while still allowing manual override. The
recommended-model lists must avoid reasoning-by-default IDs because
OpenRouter providers don't always honour `reasoning.enabled=false`.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.db import open_db, init_schema
from src.core.owners import (
    create_or_get_owner, get_owner, advance_setup_step, update_owner_field,
)
from src.bot.handlers.setup_models import (
    DEFAULT_PRIMARY,
    DEFAULT_FALLBACK,
    RECOMMENDED_FREE,
    RECOMMENDED_PAID,
    defaults_callback,
    models_command,
)


# ---------- recommended lists ---------------------------------------------

def test_default_pair_are_free_models():
    """The DEFAULT_* constants must point at `:free` IDs — the wizard
    advertises them as 'обе бесплатные'."""
    assert DEFAULT_PRIMARY.endswith(":free")
    assert DEFAULT_FALLBACK.endswith(":free")


def test_default_pair_appears_in_recommended_free():
    """The defaults sit at the top of the manual picker so users who tap
    'Изменить' still see them as the first option."""
    assert RECOMMENDED_FREE[0] == DEFAULT_PRIMARY
    assert RECOMMENDED_FREE[1] == DEFAULT_FALLBACK


def test_recommended_free_excludes_known_reasoning_ids():
    """Reasoning-by-default models silently consume max_tokens on hidden
    reasoning tokens and return empty content. They must not appear in
    the curated free list — even with reasoning.enabled=false in the
    request, OpenRouter providers don't always honour that flag."""
    banned_substrings = (
        "deepseek-r1",
        "nemotron-reasoning",
        "gpt-oss",
        "gpt-5-mini",
    )
    for mid in RECOMMENDED_FREE:
        for ban in banned_substrings:
            assert ban not in mid.lower(), f"reasoning ID leaked into free list: {mid}"


def test_recommended_paid_has_only_paid_ids():
    """Paid list must not contain `:free` suffixes — that's a sign of
    list-cross-contamination."""
    for mid in RECOMMENDED_PAID:
        assert not mid.endswith(":free"), mid


# ---------- defaults_callback ---------------------------------------------

def _make_ctx(conn, owner_telegram_id: int):
    settings = MagicMock(owner_telegram_id=owner_telegram_id)
    ctx = MagicMock()
    ctx.application.bot_data = {"settings": settings, "conn": conn}
    return ctx


def _make_callback_update(data: str, owner_telegram_id: int):
    update = MagicMock()
    update.effective_user.id = owner_telegram_id
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_defaults_use_persists_pair_and_advances(tmp_path):
    """Tap 'Использовать' → both fields saved, setup_step → 'github',
    next prompt sent."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    advance_setup_step(conn, 42, "models")

    update = _make_callback_update("defaults:use", 42)
    ctx = _make_ctx(conn, 42)

    await defaults_callback(update, ctx)

    owner = get_owner(conn, 42)
    assert owner.primary_model == DEFAULT_PRIMARY
    assert owner.fallback_model == DEFAULT_FALLBACK
    assert owner.setup_step == "github"
    update.callback_query.edit_message_text.assert_awaited_once()
    update.callback_query.message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_defaults_change_does_not_persist(tmp_path):
    """Tap 'Изменить' → nothing saved yet, setup_step stays 'models',
    user is taken to the manual picker (which itself loads the model
    list from OpenRouter — we verify only that no fields were written)."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    advance_setup_step(conn, 42, "models")
    # Save the openrouter key so _send_role_picker doesn't bail early.
    update_owner_field(conn, 42, "openrouter_key", "sk-or-test")

    update = _make_callback_update("defaults:change", 42)
    ctx = _make_ctx(conn, 42)

    # Stub out OpenRouter network call from _send_role_picker.
    from unittest.mock import patch
    with patch("src.bot.handlers.setup_models.OpenRouterClient") as mock_cls:
        mock_cls.return_value.list_models = AsyncMock(return_value=[])
        await defaults_callback(update, ctx)

    owner = get_owner(conn, 42)
    assert owner.primary_model is None
    assert owner.fallback_model is None
    assert owner.setup_step == "models"


@pytest.mark.asyncio
async def test_defaults_callback_ignored_for_non_owner(tmp_path):
    """owner_only decorator drops callbacks from strangers; nothing changes."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    advance_setup_step(conn, 42, "models")

    update = _make_callback_update("defaults:use", 999)  # not the owner
    ctx = _make_ctx(conn, 42)

    await defaults_callback(update, ctx)

    owner = get_owner(conn, 42)
    assert owner.primary_model is None
    update.callback_query.edit_message_text.assert_not_called()


# ---------- models_command branching --------------------------------------

@pytest.mark.asyncio
async def test_models_command_shows_defaults_during_initial_wizard(tmp_path):
    """First /models call inside the wizard (setup_step='models',
    primary still empty) → show one-tap defaults dialog, do NOT open
    the manual picker yet."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    advance_setup_step(conn, 42, "models")

    update = MagicMock()
    update.effective_user.id = 42
    update.message.reply_text = AsyncMock()
    ctx = _make_ctx(conn, 42)

    await models_command(update, ctx)

    update.message.reply_text.assert_awaited_once()
    args, kwargs = update.message.reply_text.call_args
    assert "Рекомендую" in args[0]
    assert DEFAULT_PRIMARY in args[0]
    assert DEFAULT_FALLBACK in args[0]
    # Reply must carry the inline keyboard with the two defaults buttons.
    kb = kwargs["reply_markup"]
    button_data = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "defaults:use" in button_data
    assert "defaults:change" in button_data


@pytest.mark.asyncio
async def test_models_command_opens_picker_after_setup(tmp_path):
    """After setup is done, /models is a re-edit entry point — it must
    skip the defaults dialog and go straight to the manual picker so
    the user can change a single role without re-confirming the pair."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    advance_setup_step(conn, 42, "done")
    update_owner_field(conn, 42, "openrouter_key", "sk-or-test")
    update_owner_field(conn, 42, "primary_model", DEFAULT_PRIMARY)
    update_owner_field(conn, 42, "fallback_model", DEFAULT_FALLBACK)

    update = MagicMock()
    update.effective_user.id = 42
    update.message.reply_text = AsyncMock()
    ctx = _make_ctx(conn, 42)

    from unittest.mock import patch
    with patch("src.bot.handlers.setup_models.OpenRouterClient") as mock_cls:
        mock_cls.return_value.list_models = AsyncMock(return_value=[])
        await models_command(update, ctx)

    args, _ = update.message.reply_text.call_args
    assert "Рекомендую" not in args[0]
    # Picker prompt asks to choose a role; either substring is fine.
    assert "модель" in args[0].lower()
