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


@pytest.mark.asyncio
async def test_list_tools_includes_new_read_api():
    from src.mcp.server import _build_tools
    names = [t.name for t in _build_tools()]
    for n in ("find_similar", "get_context", "get_by_ids", "stats"):
        assert n in names


@pytest.mark.asyncio
async def test_search_tool_advertises_date_filters():
    from src.mcp.server import _build_tools
    search = next(t for t in _build_tools() if t.name == "search")
    props = search.inputSchema["properties"]
    assert "date_from" in props
    assert "date_to" in props


@pytest.mark.asyncio
async def test_tool_get_by_ids_preserves_input_order(tmp_path):
    import time
    from src.core.db import open_db, init_schema
    from src.core.owners import create_or_get_owner
    from src.core.notes import insert_note
    from src.core.models import Note
    from src.mcp.server import tool_get_by_ids

    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    for i in (1, 2, 3):
        insert_note(conn, Note(
            owner_id=42, tg_message_id=i, tg_chat_id=-100,
            kind="post", content=f"sample {i}", created_at=int(time.time()),
        ))
    out = await tool_get_by_ids(conn, owner_id=42, ids=[3, 1, 2])
    assert [n["id"] for n in out] == [3, 1, 2]


@pytest.mark.asyncio
async def test_tool_get_context_returns_neighbors(tmp_path):
    import time
    from src.core.db import open_db, init_schema
    from src.core.owners import create_or_get_owner
    from src.core.notes import insert_note
    from src.core.models import Note
    from src.mcp.server import tool_get_context

    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    ids = []
    for i in (100, 101, 102):
        ids.append(insert_note(conn, Note(
            owner_id=42, tg_message_id=i, tg_chat_id=-100,
            kind="post", content=f"msg {i}", created_at=int(time.time()),
        )))
    # context around the middle one (id of 101): expect 100 and 102
    out = await tool_get_context(conn, owner_id=42, note_id=ids[1], window=5)
    assert sorted(n["tg_message_id"] for n in out) == [100, 102]


@pytest.mark.asyncio
async def test_tool_find_similar_returns_neighbor_list(tmp_path):
    import time
    from src.core.db import open_db, init_schema
    from src.core.owners import create_or_get_owner
    from src.core.notes import insert_note
    from src.core.vec import upsert_embedding
    from src.core.models import Note
    from src.mcp.server import tool_find_similar

    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)

    src_id = insert_note(conn, Note(
        owner_id=42, tg_message_id=1, tg_chat_id=-100,
        kind="post", content="source", created_at=int(time.time()),
    ))
    upsert_embedding(conn, src_id, [1.0] * 1024)
    near_id = insert_note(conn, Note(
        owner_id=42, tg_message_id=2, tg_chat_id=-100,
        kind="post", content="near", created_at=int(time.time()),
    ))
    upsert_embedding(conn, near_id, [1.01] * 1024)

    out = await tool_find_similar(conn, owner_id=42, note_id=src_id, limit=5)
    assert isinstance(out, list)
    assert all("id" in n for n in out)
    assert src_id not in [n["id"] for n in out]


@pytest.mark.asyncio
async def test_tool_stats_returns_iso_dates(tmp_path):
    from src.core.db import open_db, init_schema
    from src.core.owners import create_or_get_owner
    from src.core.notes import insert_note
    from src.core.models import Note
    from src.mcp.server import tool_stats

    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    insert_note(conn, Note(
        owner_id=42, tg_message_id=1, tg_chat_id=-100,
        kind="post", content="x", created_at=1_700_000_000,
    ))

    out = await tool_stats(conn, owner_id=42)
    assert out["total"] == 1
    assert "by_kind" in out
    assert isinstance(out["oldest_at"], str) and "T" in out["oldest_at"]
    assert isinstance(out["newest_at"], str) and "T" in out["newest_at"]
