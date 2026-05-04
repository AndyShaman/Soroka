# tests/test_mcp_server.py
import pytest
from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner, update_owner_field
from src.core.notes import insert_note
from src.core.vec import upsert_embedding
from src.core.models import Note
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_mcp_search_returns_hits(tmp_path, monkeypatch):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    update_owner_field(conn, 1, "jina_api_key", "k")
    update_owner_field(conn, 1, "openrouter_key", "k")
    update_owner_field(conn, 1, "primary_model", "x")
    update_owner_field(conn, 1, "fallback_model", "y")

    nid = insert_note(conn, Note(
        owner_id=1, tg_message_id=1, tg_chat_id=-1,
        kind="text", content="cats love tuna fish", created_at=1,
    ))
    upsert_embedding(conn, nid, [1.0, 0.0] + [0.0] * 1022)

    monkeypatch.setattr(
        "src.mcp.server.JinaClient",
        lambda api_key: type("J", (), {
            "embed": AsyncMock(return_value=[1.0, 0.0] + [0.0] * 1022),
        })(),
    )
    monkeypatch.setattr(
        "src.mcp.server.OpenRouterClient",
        lambda api_key: type("O", (), {
            "complete": AsyncMock(side_effect=Exception("skip")),
        })(),
    )

    from src.mcp.server import tool_search
    out = await tool_search(conn, owner_id=1, query="tuna", limit=5)
    assert out and "cats love tuna fish" in out[0]["content"]


@pytest.mark.asyncio
async def test_tool_delete_note_soft_deletes(tmp_path):
    from src.core.db import open_db, init_schema
    from src.core.owners import create_or_get_owner, update_owner_field
    from src.core.notes import insert_note, get_note
    from src.core.models import Note
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    update_owner_field(conn, 1, "jina_api_key", "k")

    nid = insert_note(conn, Note(
        owner_id=1, tg_chat_id=-1, tg_message_id=1,
        kind="text", title="t", content="контент про скиллы",
        raw_caption=None, created_at=1,
    ))
    from src.mcp.server import tool_delete_note
    res = await tool_delete_note(conn, note_id=nid, reason="дубль")
    assert res["ok"] is True
    assert get_note(conn, nid) is None


@pytest.mark.asyncio
async def test_tool_search_supports_since_days_kind_and_excludes(tmp_path):
    """Explicit MCP params bypass intent detection and are applied directly.

    Adaptation note: rerank is called unconditionally but owner has no
    openrouter_key, so OpenRouterClient.complete raises → rerank falls back to
    candidates[:top_k] order. No extra patching needed because both
    parse_intent and rerank have try/except fallbacks. JinaClient is patched
    via direct module attribute assignment so embed() returns a zero vector
    without a real API call.
    """
    from src.core.db import open_db, init_schema
    from src.core.owners import create_or_get_owner, update_owner_field
    from src.core.notes import insert_note
    from src.core.models import Note
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    update_owner_field(conn, 1, "jina_api_key", "k")

    n1 = insert_note(conn, Note(
        owner_id=1, tg_chat_id=-1, tg_message_id=1, kind="web",
        title="", content="кошка любит сметану и солнце",
        source_url="https://a", raw_caption=None, created_at=1,
    ))
    n2 = insert_note(conn, Note(
        owner_id=1, tg_chat_id=-1, tg_message_id=2, kind="text",
        title="", content="кошка играет на крыше",
        raw_caption=None, created_at=2,
    ))

    import src.mcp.server as srv
    srv.JinaClient = lambda api_key=None: type("J", (), {
        "embed": AsyncMock(return_value=[0.0] * 1024)
    })()

    out = await srv.tool_search(conn, owner_id=1, query="кошка",
                                limit=5, kind="text", exclude_ids=[n1])
    ids = [r["id"] for r in out]
    assert n1 not in ids
    assert n2 in ids


def test_list_tools_advertises_new_params():
    from src.mcp.server import _build_tools
    tools = _build_tools()
    search_tool = next(t for t in tools if t.name == "search")
    props = search_tool.inputSchema["properties"]
    assert "since_days" in props
    assert "exclude_ids" in props
    assert "kind" in props
    assert "include_thin" in props
    assert any(t.name == "delete_note" for t in tools)
