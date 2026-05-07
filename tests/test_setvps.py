"""Tests for /setvps parser and /mcp config generator.

The parser accepts two shapes — a bare ssh-config alias, or `user@host`
— and rejects anything else (including shell metacharacters that could
poison the MCP config). The /mcp generator must omit the `user@`
prefix in alias mode so ssh resolves user/host/key from ~/.ssh/config.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.db import open_db, init_schema
from src.core.owners import (
    create_or_get_owner, get_owner, update_owner_field,
)
from src.bot.handlers.commands import (
    _parse_vps_input,
    pending_set_handler,
    mcp_command,
    VPS_PROMPT,
)


# ---------- _parse_vps_input ----------------------------------------------

def test_parse_alias_only():
    """Bare alias → vps_user is None, host carries the alias verbatim."""
    assert _parse_vps_input("myserver") == (None, "myserver")
    assert _parse_vps_input("my-vps_01.prod") == (None, "my-vps_01.prod")


def test_parse_user_at_host():
    assert _parse_vps_input("ubuntu@198.51.100.42") == ("ubuntu", "198.51.100.42")
    assert _parse_vps_input("andy@vps.example.com") == ("andy", "vps.example.com")


def test_parse_strips_whitespace():
    assert _parse_vps_input("  myserver  ") == (None, "myserver")
    assert _parse_vps_input("\tubuntu@1.2.3.4\n") == ("ubuntu", "1.2.3.4")


def test_parse_rejects_empty():
    assert _parse_vps_input("") is None
    assert _parse_vps_input("   ") is None


def test_parse_rejects_internal_whitespace():
    """A space inside the token would split into two argv pieces and
    confuse `ssh` — reject up front."""
    assert _parse_vps_input("my server") is None
    assert _parse_vps_input("user @host") is None


def test_parse_rejects_shell_metacharacters():
    """argv-mode insulates us from shells, but Claude Desktop renders
    the config to JSON which a careless reader could copy into a shell.
    Reject metachars defensively."""
    for evil in [
        "host;ls",
        "host|cat",
        "host&disown",
        "host`whoami`",
        "host$(id)",
        "user@host;rm",
        '"quoted"',
        "../etc/passwd",
        "host with space",
    ]:
        assert _parse_vps_input(evil) is None, evil


def test_parse_rejects_empty_user_or_host_part():
    assert _parse_vps_input("@host") is None
    assert _parse_vps_input("user@") is None
    assert _parse_vps_input("@") is None


def test_parse_rejects_multiple_at_signs():
    """`a@b@c` is ambiguous — partition keeps `b@c` as host, which
    contains `@` and fails the host regex. Verified explicitly."""
    assert _parse_vps_input("a@b@c") is None


# ---------- /setvps handler integration -----------------------------------

def _make_ctx(conn, owner_telegram_id: int):
    settings = MagicMock(owner_telegram_id=owner_telegram_id)
    ctx = MagicMock()
    ctx.application.bot_data = {"settings": settings, "conn": conn}
    ctx.user_data = {"pending_set": "vps"}
    return ctx


def _make_text_update(text: str, owner_telegram_id: int):
    update = MagicMock()
    update.effective_user.id = owner_telegram_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_setvps_saves_alias_with_null_user(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)

    ctx = _make_ctx(conn, 42)
    update = _make_text_update("myserver", 42)

    await pending_set_handler(update, ctx)

    owner = get_owner(conn, 42)
    assert owner.vps_host == "myserver"
    assert owner.vps_user is None
    assert ctx.user_data.get("pending_set") is None


@pytest.mark.asyncio
async def test_setvps_saves_user_at_host(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)

    ctx = _make_ctx(conn, 42)
    update = _make_text_update("ubuntu@198.51.100.42", 42)

    await pending_set_handler(update, ctx)

    owner = get_owner(conn, 42)
    assert owner.vps_user == "ubuntu"
    assert owner.vps_host == "198.51.100.42"


@pytest.mark.asyncio
async def test_setvps_rejects_invalid_input_keeps_pending(tmp_path):
    """Bad input — owner record stays untouched, pending_set survives so
    the user can retry without typing /setvps again."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)

    ctx = _make_ctx(conn, 42)
    update = _make_text_update("host;rm -rf /", 42)

    await pending_set_handler(update, ctx)

    owner = get_owner(conn, 42)
    assert owner.vps_host is None
    assert owner.vps_user is None
    assert ctx.user_data["pending_set"] == "vps"
    update.message.reply_text.assert_awaited_once()


def test_vps_prompt_does_not_hardcode_real_hostnames():
    """Prompt should use illustrative names only — no operator hosts
    like `myvps` baked into user-visible text."""
    assert "myvps" not in VPS_PROMPT
    # Sanity: prompt actually mentions both supported formats.
    assert "myserver" in VPS_PROMPT
    assert "@" in VPS_PROMPT


# ---------- /mcp generator ------------------------------------------------

@pytest.mark.asyncio
async def test_mcp_alias_mode_emits_bare_host(tmp_path):
    """When vps_user is NULL, the generated args carry just the host
    so `ssh myserver soroka-mcp` lets ~/.ssh/config resolve user/key."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    update_owner_field(conn, 42, "vps_host", "myserver")

    ctx = _make_ctx(conn, 42)
    ctx.user_data = {}  # /mcp doesn't need pending_set
    update = MagicMock()
    update.effective_user.id = 42
    update.message.reply_text = AsyncMock()

    await mcp_command(update, ctx)

    sent = update.message.reply_text.call_args[0][0]
    assert '"args": ["myserver", "soroka-mcp"]' in sent
    assert "@" not in sent.split('"args"')[1].split("]")[0]


@pytest.mark.asyncio
async def test_mcp_user_host_mode_emits_user_at_host(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    update_owner_field(conn, 42, "vps_user", "ubuntu")
    update_owner_field(conn, 42, "vps_host", "198.51.100.42")

    ctx = _make_ctx(conn, 42)
    ctx.user_data = {}
    update = MagicMock()
    update.effective_user.id = 42
    update.message.reply_text = AsyncMock()

    await mcp_command(update, ctx)

    sent = update.message.reply_text.call_args[0][0]
    assert '"args": ["ubuntu@198.51.100.42", "soroka-mcp"]' in sent


@pytest.mark.asyncio
async def test_mcp_without_vps_host_asks_for_setvps(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)

    ctx = _make_ctx(conn, 42)
    ctx.user_data = {}
    update = MagicMock()
    update.effective_user.id = 42
    update.message.reply_text = AsyncMock()

    await mcp_command(update, ctx)

    sent = update.message.reply_text.call_args[0][0]
    assert "/setvps" in sent
    assert "soroka-mcp" not in sent
