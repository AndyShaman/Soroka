import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from src.adapters.jina import JinaClient
from src.adapters.openrouter import OpenRouterClient
from src.core.db import open_db, init_schema
from src.core.intent import parse_intent
from src.core.links import message_link
from src.core.neighbors import find_similar, get_context, get_by_ids
from src.core.notes import get_note, list_recent_notes
from src.core.owners import get_owner
from src.core.search import hybrid_search, rerank
from src.core.stats import compute_stats
from src.core.attachments import list_attachments

DB_PATH = Path("/app/data/soroka.db")


def _note_to_dict(n) -> dict:
    return {
        "id": n.id,
        "kind": n.kind,
        "title": n.title,
        "content": n.content,
        "source_url": n.source_url,
        "tg_message_id": n.tg_message_id,
        "tg_chat_id": n.tg_chat_id,
        "tg_link": message_link(n.tg_chat_id, n.tg_message_id),
        "created_at": n.created_at,
    }


def _epoch_to_iso(epoch):
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _iso_date_to_epoch(date_str, end_of_day: bool):
    if not date_str:
        return None
    d = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    if end_of_day:
        d = d.replace(hour=23, minute=59, second=59)
    return int(d.timestamp())


async def tool_search(conn: sqlite3.Connection, owner_id: int,
                      query: str, limit: int = 5,
                      kind: Optional[str] = None,
                      since_days: Optional[int] = None,
                      exclude_ids: Optional[list[int]] = None,
                      offset: int = 0,
                      include_thin: bool = False,
                      created_after: Optional[int] = None,
                      created_before: Optional[int] = None) -> list[dict]:
    """Hybrid search exposed via MCP. Explicit `kind` / `since_days` /
    `exclude_ids` skip intent detection (saves tokens; agents already
    know what they want)."""
    owner = get_owner(conn, owner_id)
    jina = JinaClient(api_key=owner.jina_api_key)
    openrouter = OpenRouterClient(api_key=owner.openrouter_key)

    explicit = kind is not None or since_days is not None
    if explicit:
        clean_query = query
        eff_kind = kind
    else:
        intent = await parse_intent(
            openrouter, primary=owner.primary_model,
            fallback=owner.fallback_model, query=query,
        )
        clean_query = intent.clean_query
        eff_kind = intent.kind

    candidates = await hybrid_search(
        conn, jina=jina, owner_id=owner_id,
        clean_query=clean_query, kind=eff_kind, limit=15,
        since_days=since_days, exclude_ids=exclude_ids or [],
        offset=offset, include_thin=include_thin,
        created_after=created_after, created_before=created_before,
    )
    reranked = await rerank(
        openrouter, primary=owner.primary_model, fallback=owner.fallback_model,
        query=clean_query, candidates=candidates, top_k=limit,
    )
    return [{
        "id": n.id, "kind": n.kind, "title": n.title,
        "content": n.content, "source_url": n.source_url,
        "tg_link": message_link(n.tg_chat_id, n.tg_message_id),
        "created_at": n.created_at,
    } for n in reranked]


async def tool_get_by_id(conn: sqlite3.Connection, note_id: int) -> dict | None:
    n = get_note(conn, note_id)
    if not n:
        return None
    return n.model_dump()


async def tool_list_recent(conn: sqlite3.Connection, owner_id: int,
                           limit: int = 20, kind: Optional[str] = None,
                           since_days: Optional[int] = None) -> list[dict]:
    notes = list_recent_notes(conn, owner_id=owner_id, limit=limit, kind=kind)
    if since_days is not None:
        import time
        cutoff = int(time.time()) - since_days * 86400
        notes = [n for n in notes if n.created_at >= cutoff]
    return [n.model_dump() for n in notes]


async def tool_get_attachment(conn: sqlite3.Connection, note_id: int) -> dict:
    atts = list_attachments(conn, note_id)
    if not atts:
        return {"error": "no attachment"}
    a = atts[0]
    if a.is_oversized:
        return {"error": "oversized", "original_name": a.original_name}
    p = Path(a.file_path)
    import base64
    return {
        "original_name": a.original_name,
        "mime_type": a.mime_type,
        "size": a.file_size,
        "content_base64": base64.b64encode(p.read_bytes()).decode(),
    }


async def tool_delete_note(conn: sqlite3.Connection, *, note_id: int,
                           reason: str) -> dict:
    """Soft-delete a note. The row stays for possible recovery via raw
    SQL; everything user-facing hides it. Reason is logged for audit."""
    from src.core.notes import soft_delete_note
    ok = soft_delete_note(conn, note_id, reason=reason)
    return {"ok": ok, "note_id": note_id, "reason": reason}


async def tool_find_similar(conn: sqlite3.Connection, owner_id: int,
                            note_id: int, limit: int = 5) -> list[dict]:
    notes = await find_similar(conn, owner_id=owner_id,
                               note_id=note_id, limit=limit)
    return [_note_to_dict(n) for n in notes]


async def tool_get_context(conn: sqlite3.Connection, owner_id: int,
                           note_id: int, window: int = 3) -> list[dict]:
    notes = get_context(conn, owner_id=owner_id, note_id=note_id, window=window)
    return [_note_to_dict(n) for n in notes]


async def tool_get_by_ids(conn: sqlite3.Connection, owner_id: int,
                          ids: list[int]) -> list[dict]:
    notes = get_by_ids(conn, owner_id=owner_id, ids=ids)
    return [_note_to_dict(n) for n in notes]


async def tool_stats(conn: sqlite3.Connection, owner_id: int) -> dict:
    s = compute_stats(conn, owner_id)
    return {
        "total": s.total,
        "last_day": s.last_day,
        "last_week": s.last_week,
        "last_month": s.last_month,
        "by_kind": s.by_kind,
        "oldest_at": _epoch_to_iso(s.oldest_at),
        "newest_at": _epoch_to_iso(s.newest_at),
    }


def _build_tools() -> list[Tool]:
    return [
        Tool(name="search",
             description="Hybrid search over the knowledge base. "
                         "Explicit kind/since_days bypass LLM intent detection.",
             inputSchema={"type": "object", "properties": {
                 "query": {"type": "string"},
                 "limit": {"type": "integer", "default": 5},
                 "kind": {"type": "string",
                          "enum": ["text", "web", "youtube", "voice",
                                   "pdf", "docx", "xlsx", "image", "post"]},
                 "since_days": {"type": "integer",
                                "description": "Only notes created within N days"},
                 "exclude_ids": {"type": "array", "items": {"type": "integer"}},
                 "offset": {"type": "integer", "default": 0},
                 "include_thin": {"type": "boolean", "default": False,
                                  "description": "Include extractor-flagged "
                                                 "thin_content notes"},
                 "date_from": {"type": "string",
                               "description": "ISO YYYY-MM-DD (inclusive lower bound)"},
                 "date_to": {"type": "string",
                             "description": "ISO YYYY-MM-DD (inclusive upper bound)"},
             }, "required": ["query"]}),
        Tool(name="get_by_id", description="Fetch full note by id.",
             inputSchema={"type": "object", "properties": {
                 "note_id": {"type": "integer"},
             }, "required": ["note_id"]}),
        Tool(name="list_recent", description="List most recent notes.",
             inputSchema={"type": "object", "properties": {
                 "limit": {"type": "integer", "default": 20},
                 "kind": {"type": "string"},
                 "since_days": {"type": "integer"},
             }}),
        Tool(name="get_attachment", description="Fetch attachment for a note.",
             inputSchema={"type": "object", "properties": {
                 "note_id": {"type": "integer"},
             }, "required": ["note_id"]}),
        Tool(name="delete_note",
             description="Soft-delete a note. Hidden from all searches; "
                         "recoverable via raw SQL on the host. Reason is logged.",
             inputSchema={"type": "object", "properties": {
                 "note_id": {"type": "integer"},
                 "reason": {"type": "string",
                            "description": "Why this note is being deleted"},
             }, "required": ["note_id", "reason"]}),
        Tool(name="find_similar",
             description="Vector neighbors of a note. Excludes source, deleted, thin.",
             inputSchema={"type": "object", "properties": {
                 "note_id": {"type": "integer"},
                 "limit": {"type": "integer", "minimum": 1, "maximum": 20,
                           "default": 5},
             }, "required": ["note_id"]}),
        Tool(name="get_context",
             description="Sibling messages in the same Telegram chat, "
                         "+/-window around the note.",
             inputSchema={"type": "object", "properties": {
                 "note_id": {"type": "integer"},
                 "window": {"type": "integer", "minimum": 1, "maximum": 10,
                            "default": 3},
             }, "required": ["note_id"]}),
        Tool(name="get_by_ids",
             description="Batch-load notes by id. Missing ids are silently dropped.",
             inputSchema={"type": "object", "properties": {
                 "ids": {"type": "array", "items": {"type": "integer"},
                         "minItems": 1, "maxItems": 100},
             }, "required": ["ids"]}),
        Tool(name="stats",
             description="Aggregate stats: totals, time windows, by-kind breakdown.",
             inputSchema={"type": "object", "properties": {}}),
    ]


def _server(conn: sqlite3.Connection, owner_id: int) -> Server:
    server = Server("soroka")

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return _build_tools()

    @server.call_tool()
    async def _call_tool(name: str, args: dict) -> list[TextContent]:
        import json
        if name == "search":
            data = await tool_search(
                conn, owner_id, args["query"],
                limit=args.get("limit", 5),
                kind=args.get("kind"),
                since_days=args.get("since_days"),
                exclude_ids=args.get("exclude_ids"),
                offset=args.get("offset", 0),
                include_thin=args.get("include_thin", False),
                created_after=_iso_date_to_epoch(args.get("date_from"),
                                                 end_of_day=False),
                created_before=_iso_date_to_epoch(args.get("date_to"),
                                                  end_of_day=True),
            )
        elif name == "get_by_id":
            data = await tool_get_by_id(conn, args["note_id"])
        elif name == "list_recent":
            data = await tool_list_recent(
                conn, owner_id,
                limit=args.get("limit", 20),
                kind=args.get("kind"),
                since_days=args.get("since_days"),
            )
        elif name == "get_attachment":
            data = await tool_get_attachment(conn, args["note_id"])
        elif name == "delete_note":
            data = await tool_delete_note(
                conn, note_id=args["note_id"], reason=args["reason"],
            )
        elif name == "find_similar":
            data = await tool_find_similar(
                conn, owner_id, args["note_id"],
                limit=args.get("limit", 5),
            )
        elif name == "get_context":
            data = await tool_get_context(
                conn, owner_id, args["note_id"],
                window=args.get("window", 3),
            )
        elif name == "get_by_ids":
            data = await tool_get_by_ids(conn, owner_id, args["ids"])
        elif name == "stats":
            data = await tool_stats(conn, owner_id)
        else:
            data = {"error": "unknown tool"}
        return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]

    return server


async def _main_async():
    import os
    owner_id = int(os.environ["OWNER_TELEGRAM_ID"])
    conn = open_db(str(DB_PATH))
    init_schema(conn)
    server = _server(conn, owner_id)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main():
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
