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
