import asyncio
import sqlite3
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from src.adapters.jina import JinaClient
from src.adapters.openrouter import OpenRouterClient
from src.core.db import open_db, init_schema
from src.core.intent import parse_intent
from src.core.links import message_link
from src.core.notes import get_note, list_recent_notes
from src.core.owners import get_owner
from src.core.search import hybrid_search, rerank
from src.core.attachments import list_attachments

DB_PATH = Path("/app/data/soroka.db")


async def tool_search(conn: sqlite3.Connection, owner_id: int,
                      query: str, limit: int = 5) -> list[dict]:
    owner = get_owner(conn, owner_id)
    jina = JinaClient(api_key=owner.jina_api_key)
    openrouter = OpenRouterClient(api_key=owner.openrouter_key)
    intent = await parse_intent(openrouter, primary=owner.primary_model,
                                 fallback=owner.fallback_model, query=query)
    candidates = await hybrid_search(
        conn, jina=jina, owner_id=owner_id,
        clean_query=intent.clean_query, kind=intent.kind, limit=15,
    )
    reranked = await rerank(
        openrouter, primary=owner.primary_model, fallback=owner.fallback_model,
        query=intent.clean_query, candidates=candidates, top_k=limit,
    )
    return [{
        "id": n.id,
        "kind": n.kind,
        "title": n.title,
        "content": n.content,
        "source_url": n.source_url,
        "tg_link": message_link(n.tg_chat_id, n.tg_message_id),
    } for n in reranked]


async def tool_get_by_id(conn: sqlite3.Connection, note_id: int) -> dict | None:
    n = get_note(conn, note_id)
    if not n:
        return None
    return n.model_dump()


async def tool_list_recent(conn: sqlite3.Connection, owner_id: int,
                           limit: int = 20, kind: str | None = None) -> list[dict]:
    notes = list_recent_notes(conn, owner_id=owner_id, limit=limit, kind=kind)
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


def _server(conn: sqlite3.Connection, owner_id: int) -> Server:
    server = Server("soroka")

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [
            Tool(name="search", description="Hybrid search over the knowledge base.",
                 inputSchema={"type": "object", "properties": {
                     "query": {"type": "string"},
                     "limit": {"type": "integer", "default": 5},
                 }, "required": ["query"]}),
            Tool(name="get_by_id", description="Fetch full note by id.",
                 inputSchema={"type": "object", "properties": {
                     "note_id": {"type": "integer"},
                 }, "required": ["note_id"]}),
            Tool(name="list_recent", description="List most recent notes.",
                 inputSchema={"type": "object", "properties": {
                     "limit": {"type": "integer", "default": 20},
                     "kind": {"type": "string"},
                 }}),
            Tool(name="get_attachment", description="Fetch attachment for a note.",
                 inputSchema={"type": "object", "properties": {
                     "note_id": {"type": "integer"},
                 }, "required": ["note_id"]}),
        ]

    @server.call_tool()
    async def _call_tool(name: str, args: dict) -> list[TextContent]:
        import json
        if name == "search":
            data = await tool_search(conn, owner_id, args["query"], args.get("limit", 5))
        elif name == "get_by_id":
            data = await tool_get_by_id(conn, args["note_id"])
        elif name == "list_recent":
            data = await tool_list_recent(conn, owner_id, args.get("limit", 20), args.get("kind"))
        elif name == "get_attachment":
            data = await tool_get_attachment(conn, args["note_id"])
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
