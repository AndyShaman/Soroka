# Soroka MVP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-hosted Telegram bot that turns a private "Favorites" channel into a personal knowledge base with hybrid search and an MCP server for AI agents.

**Architecture:** Python 3.12 + python-telegram-bot v22 + SQLite (FTS5 + sqlite-vec) on a single Docker container. External services: Jina v3 (embeddings), Deepgram (voice), OpenRouter (LLM, user-selectable). Layers: `core/` (pure logic), `adapters/` (external services), `bot/` (Telegram I/O), `mcp/` (MCP-over-stdio). All user secrets except `TELEGRAM_BOT_TOKEN` and `OWNER_TELEGRAM_ID` are collected via the `/start` wizard and stored in SQLite.

**Tech Stack:** Python 3.12, python-telegram-bot 22, SQLite + FTS5 + sqlite-vec, httpx, pydantic v2, trafilatura, yt-dlp, pypdf, python-docx, openpyxl, pytesseract, mcp (MCP SDK), pytest, Docker.

**Reference spec:** `docs/specs/2026-04-30-design.md`

---

## Phase 1 — Foundation (project scaffold)

### Task 1: Initial repo files

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `Dockerfile`
- Create: `docker-compose.yml`
- Create: `README.md` (placeholder; full content in Phase 11)
- Create: `src/__init__.py` (empty)
- Create: `src/core/__init__.py` (empty)
- Create: `src/adapters/__init__.py` (empty)
- Create: `src/adapters/extractors/__init__.py` (empty)
- Create: `src/bot/__init__.py` (empty)
- Create: `src/bot/handlers/__init__.py` (empty)
- Create: `src/mcp/__init__.py` (empty)
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py` (empty for now)

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "soroka"
version = "0.1.0"
description = "Telegram-bot knowledge base for forwarded content"
requires-python = ">=3.12"
dependencies = [
    "python-telegram-bot[ext]==22.*",
    "httpx==0.27.*",
    "pydantic==2.*",
    "trafilatura==1.12.*",
    "yt-dlp==2025.*",
    "pypdf==4.*",
    "python-docx==1.*",
    "openpyxl==3.*",
    "pytesseract==0.3.*",
    "Pillow==10.*",
    "sqlite-vec==0.1.*",
    "mcp==1.*",
    "python-dotenv==1.*",
]

[project.optional-dependencies]
dev = [
    "pytest==8.*",
    "pytest-asyncio==0.23.*",
    "pytest-httpx==0.30.*",
    "freezegun==1.*",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src"]
```

- [ ] **Step 2: Write `.gitignore`**

```
.env
data/
*.db
*.db-journal
*.db-shm
*.db-wal
attachments/
__pycache__/
*.pyc
.venv/
.pytest_cache/
*.egg-info/
dist/
build/
.DS_Store
```

- [ ] **Step 3: Write `.env.example`**

```
# Soroka — minimal env. Created automatically by ./bin/install.
# Everything else is configured via the bot's /start wizard.

TELEGRAM_BOT_TOKEN=
OWNER_TELEGRAM_ID=
```

- [ ] **Step 4: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng \
        ffmpeg \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY src ./src

RUN mkdir -p /app/data
VOLUME ["/app/data"]

CMD ["python", "-m", "src.bot.main"]
```

- [ ] **Step 5: Write `docker-compose.yml`**

```yaml
services:
  bot:
    build: .
    container_name: soroka-bot
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/app/data
    command: python -m src.bot.main
```

- [ ] **Step 6: Write placeholder `README.md`**

```markdown
# Soroka

Telegram-bot knowledge base. See `docs/specs/2026-04-30-design.md`.

Full README will be populated in Phase 11 of the implementation plan.
```

- [ ] **Step 7: Create empty `__init__.py` files**

```bash
mkdir -p src/core src/adapters/extractors src/bot/handlers src/mcp tests
touch src/__init__.py src/core/__init__.py src/adapters/__init__.py \
      src/adapters/extractors/__init__.py src/bot/__init__.py \
      src/bot/handlers/__init__.py src/mcp/__init__.py \
      tests/__init__.py tests/conftest.py
```

- [ ] **Step 8: Verify the package builds**

Run: `pip install -e ".[dev]"`
Expected: clean install, no errors.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml .gitignore .env.example Dockerfile docker-compose.yml README.md src tests
git commit -m "chore: project scaffold and dependencies"
```

---

## Phase 2 — Database & Models

### Task 2: Pydantic models for the domain

**Files:**
- Create: `src/core/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from src.core.models import Owner, Note, Attachment

def test_owner_has_optional_setup_fields():
    o = Owner(telegram_id=1, created_at=1700000000)
    assert o.jina_api_key is None
    assert o.setup_step is None

def test_note_kind_is_validated():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Note(
            owner_id=1, tg_message_id=1, tg_chat_id=1,
            kind="invalid", content="x", created_at=1,
        )

def test_attachment_default_not_oversized():
    a = Attachment(note_id=1, file_path="x", file_size=1)
    assert a.is_oversized is False
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_models.py -v`
Expected: FAIL — `ImportError: src.core.models`

- [ ] **Step 3: Write `src/core/models.py`**

```python
from typing import Literal, Optional
from pydantic import BaseModel, Field

NoteKind = Literal[
    "text", "voice", "youtube", "web", "pdf",
    "docx", "xlsx", "image", "oversized",
]

SetupStep = Literal[
    "jina", "deepgram", "openrouter", "models",
    "github", "channel", "done",
]


class Owner(BaseModel):
    telegram_id: int
    jina_api_key: Optional[str] = None
    deepgram_api_key: Optional[str] = None
    openrouter_key: Optional[str] = None
    primary_model: Optional[str] = None
    fallback_model: Optional[str] = None
    github_token: Optional[str] = None
    github_mirror_repo: Optional[str] = None
    vps_host: Optional[str] = None
    vps_user: Optional[str] = None
    inbox_chat_id: Optional[int] = None
    setup_step: Optional[SetupStep] = None
    created_at: int


class Note(BaseModel):
    id: Optional[int] = None
    owner_id: int
    tg_message_id: int
    tg_chat_id: int
    kind: NoteKind
    title: Optional[str] = None
    content: str
    source_url: Optional[str] = None
    raw_caption: Optional[str] = None
    created_at: int


class Attachment(BaseModel):
    id: Optional[int] = None
    note_id: int
    file_path: str
    file_size: int
    mime_type: Optional[str] = None
    original_name: Optional[str] = None
    is_oversized: bool = False
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `pytest tests/test_models.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/models.py tests/test_models.py
git commit -m "feat(core): add Pydantic models for Owner, Note, Attachment"
```

---

### Task 3: SQLite schema and connection helper

**Files:**
- Create: `src/core/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py
import sqlite3
from src.core.db import open_db, init_schema

def test_init_schema_creates_all_tables(tmp_path):
    db_path = tmp_path / "soroka.db"
    conn = open_db(str(db_path))
    init_schema(conn)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','index') ORDER BY name"
    )
    names = {row[0] for row in cur.fetchall()}
    for expected in {"owners", "notes", "attachments", "notes_fts", "notes_vec"}:
        assert expected in names

def test_init_schema_is_idempotent(tmp_path):
    db_path = tmp_path / "soroka.db"
    conn = open_db(str(db_path))
    init_schema(conn)
    init_schema(conn)  # second call must not raise

def test_owners_table_allows_null_keys(tmp_path):
    conn = open_db(str(tmp_path / "soroka.db"))
    init_schema(conn)
    conn.execute(
        "INSERT INTO owners (telegram_id, created_at) VALUES (?, ?)",
        (1, 1700000000),
    )
    conn.commit()
    row = conn.execute("SELECT jina_api_key FROM owners").fetchone()
    assert row[0] is None
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_db.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `src/core/db.py`**

```python
import sqlite3
from pathlib import Path

import sqlite_vec

SCHEMA = """
CREATE TABLE IF NOT EXISTS owners (
    telegram_id        INTEGER PRIMARY KEY,
    jina_api_key       TEXT,
    deepgram_api_key   TEXT,
    openrouter_key     TEXT,
    primary_model      TEXT,
    fallback_model     TEXT,
    github_token       TEXT,
    github_mirror_repo TEXT,
    vps_host           TEXT,
    vps_user           TEXT,
    inbox_chat_id      INTEGER,
    setup_step         TEXT,
    created_at         INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id        INTEGER NOT NULL REFERENCES owners(telegram_id),
    tg_message_id   INTEGER NOT NULL,
    tg_chat_id      INTEGER NOT NULL,
    kind            TEXT NOT NULL,
    title           TEXT,
    content         TEXT NOT NULL,
    source_url      TEXT,
    raw_caption     TEXT,
    created_at      INTEGER NOT NULL,
    UNIQUE(owner_id, tg_chat_id, tg_message_id)
);

CREATE TABLE IF NOT EXISTS attachments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id         INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    file_path       TEXT NOT NULL,
    file_size       INTEGER NOT NULL,
    mime_type       TEXT,
    original_name   TEXT,
    is_oversized    INTEGER DEFAULT 0
);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    title, content, raw_caption,
    content='notes',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 0'
);

CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, title, content, raw_caption)
    VALUES (new.id, new.title, new.content, new.raw_caption);
END;

CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, content, raw_caption)
    VALUES ('delete', old.id, old.title, old.content, old.raw_caption);
END;

CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, content, raw_caption)
    VALUES ('delete', old.id, old.title, old.content, old.raw_caption);
    INSERT INTO notes_fts(rowid, title, content, raw_caption)
    VALUES (new.id, new.title, new.content, new.raw_caption);
END;
"""

VEC_TABLE = """
CREATE VIRTUAL TABLE IF NOT EXISTS notes_vec USING vec0(
    note_id INTEGER PRIMARY KEY,
    embedding FLOAT[1024]
);
"""


def open_db(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.executescript(VEC_TABLE)
    conn.commit()
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `pytest tests/test_db.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/db.py tests/test_db.py
git commit -m "feat(core): SQLite schema with FTS5 and sqlite-vec"
```

---

### Task 4: Owner repository (read/update settings)

**Files:**
- Create: `src/core/owners.py`
- Create: `tests/test_owners.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_owners.py
from src.core.db import open_db, init_schema
from src.core.owners import (
    create_or_get_owner, get_owner, update_owner_field, advance_setup_step,
)

def test_create_or_get_owner_inserts_once(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    o1 = create_or_get_owner(conn, telegram_id=42)
    o2 = create_or_get_owner(conn, telegram_id=42)
    assert o1.telegram_id == o2.telegram_id == 42
    rows = conn.execute("SELECT count(*) FROM owners").fetchone()
    assert rows[0] == 1

def test_update_owner_field_round_trip(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    update_owner_field(conn, 42, "jina_api_key", "abc")
    o = get_owner(conn, 42)
    assert o.jina_api_key == "abc"

def test_advance_setup_step_writes_step(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    advance_setup_step(conn, 42, "jina")
    assert get_owner(conn, 42).setup_step == "jina"
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_owners.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write `src/core/owners.py`**

```python
import sqlite3
import time
from typing import Optional

from src.core.models import Owner, SetupStep

ALLOWED_FIELDS = {
    "jina_api_key", "deepgram_api_key", "openrouter_key",
    "primary_model", "fallback_model",
    "github_token", "github_mirror_repo",
    "vps_host", "vps_user", "inbox_chat_id", "setup_step",
}


def create_or_get_owner(conn: sqlite3.Connection, telegram_id: int) -> Owner:
    conn.execute(
        "INSERT OR IGNORE INTO owners (telegram_id, created_at) VALUES (?, ?)",
        (telegram_id, int(time.time())),
    )
    conn.commit()
    return get_owner(conn, telegram_id)


def get_owner(conn: sqlite3.Connection, telegram_id: int) -> Optional[Owner]:
    cur = conn.execute(
        """SELECT telegram_id, jina_api_key, deepgram_api_key, openrouter_key,
                  primary_model, fallback_model, github_token, github_mirror_repo,
                  vps_host, vps_user, inbox_chat_id, setup_step, created_at
           FROM owners WHERE telegram_id = ?""",
        (telegram_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    fields = (
        "telegram_id jina_api_key deepgram_api_key openrouter_key "
        "primary_model fallback_model github_token github_mirror_repo "
        "vps_host vps_user inbox_chat_id setup_step created_at"
    ).split()
    return Owner(**dict(zip(fields, row)))


def update_owner_field(conn: sqlite3.Connection, telegram_id: int, field: str, value) -> None:
    if field not in ALLOWED_FIELDS:
        raise ValueError(f"unknown field: {field}")
    conn.execute(
        f"UPDATE owners SET {field} = ? WHERE telegram_id = ?",
        (value, telegram_id),
    )
    conn.commit()


def advance_setup_step(conn: sqlite3.Connection, telegram_id: int, step: SetupStep) -> None:
    update_owner_field(conn, telegram_id, "setup_step", step)
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `pytest tests/test_owners.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/core/owners.py tests/test_owners.py
git commit -m "feat(core): owners repository with field updates"
```

---

### Task 5: Notes & attachments repository

**Files:**
- Create: `src/core/notes.py`
- Create: `tests/test_notes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_notes.py
from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner
from src.core.notes import insert_note, get_note, list_recent_notes
from src.core.models import Note

def _fixture_conn(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    return conn

def test_insert_note_returns_id(tmp_path):
    conn = _fixture_conn(tmp_path)
    n = Note(owner_id=1, tg_message_id=10, tg_chat_id=-100,
             kind="text", content="hello", created_at=1)
    note_id = insert_note(conn, n)
    assert note_id == 1
    fetched = get_note(conn, note_id)
    assert fetched.content == "hello"

def test_insert_note_dedupes_by_message(tmp_path):
    conn = _fixture_conn(tmp_path)
    n = Note(owner_id=1, tg_message_id=10, tg_chat_id=-100,
             kind="text", content="hello", created_at=1)
    insert_note(conn, n)
    second_id = insert_note(conn, n)
    assert second_id is None  # duplicate

def test_list_recent_notes_orders_desc(tmp_path):
    conn = _fixture_conn(tmp_path)
    for i in range(3):
        insert_note(conn, Note(
            owner_id=1, tg_message_id=i, tg_chat_id=-100,
            kind="text", content=f"n{i}", created_at=1000 + i,
        ))
    rows = list_recent_notes(conn, owner_id=1, limit=10)
    assert [n.content for n in rows] == ["n2", "n1", "n0"]
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_notes.py -v`

- [ ] **Step 3: Write `src/core/notes.py`**

```python
import sqlite3
from typing import Optional

from src.core.models import Note


def insert_note(conn: sqlite3.Connection, note: Note) -> Optional[int]:
    cur = conn.execute(
        """INSERT OR IGNORE INTO notes
           (owner_id, tg_message_id, tg_chat_id, kind, title, content,
            source_url, raw_caption, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (note.owner_id, note.tg_message_id, note.tg_chat_id, note.kind,
         note.title, note.content, note.source_url, note.raw_caption,
         note.created_at),
    )
    conn.commit()
    if cur.rowcount == 0:
        return None
    return cur.lastrowid


def get_note(conn: sqlite3.Connection, note_id: int) -> Optional[Note]:
    cur = conn.execute(
        """SELECT id, owner_id, tg_message_id, tg_chat_id, kind, title, content,
                  source_url, raw_caption, created_at
           FROM notes WHERE id = ?""",
        (note_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    fields = "id owner_id tg_message_id tg_chat_id kind title content source_url raw_caption created_at".split()
    return Note(**dict(zip(fields, row)))


def list_recent_notes(conn: sqlite3.Connection, owner_id: int, limit: int = 20,
                      kind: Optional[str] = None) -> list[Note]:
    if kind:
        cur = conn.execute(
            """SELECT id, owner_id, tg_message_id, tg_chat_id, kind, title, content,
                      source_url, raw_caption, created_at
               FROM notes WHERE owner_id = ? AND kind = ?
               ORDER BY created_at DESC LIMIT ?""",
            (owner_id, kind, limit),
        )
    else:
        cur = conn.execute(
            """SELECT id, owner_id, tg_message_id, tg_chat_id, kind, title, content,
                      source_url, raw_caption, created_at
               FROM notes WHERE owner_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (owner_id, limit),
        )
    fields = "id owner_id tg_message_id tg_chat_id kind title content source_url raw_caption created_at".split()
    return [Note(**dict(zip(fields, row))) for row in cur.fetchall()]
```

- [ ] **Step 4: Run tests, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/core/notes.py tests/test_notes.py
git commit -m "feat(core): notes repository (insert with dedup, get, list_recent)"
```

---

### Task 6: Attachments repository

**Files:**
- Create: `src/core/attachments.py`
- Create: `tests/test_attachments.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_attachments.py
from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner
from src.core.notes import insert_note
from src.core.attachments import insert_attachment, list_attachments
from src.core.models import Note, Attachment

def test_insert_and_list_attachment(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    note_id = insert_note(conn, Note(
        owner_id=1, tg_message_id=1, tg_chat_id=-1,
        kind="pdf", content="x", created_at=1,
    ))
    insert_attachment(conn, Attachment(
        note_id=note_id, file_path="data/x.pdf",
        file_size=10, original_name="x.pdf",
    ))
    attachments = list_attachments(conn, note_id)
    assert len(attachments) == 1
    assert attachments[0].original_name == "x.pdf"
```

- [ ] **Step 2: Run test, expect failure**

- [ ] **Step 3: Write `src/core/attachments.py`**

```python
import sqlite3
from src.core.models import Attachment


def insert_attachment(conn: sqlite3.Connection, att: Attachment) -> int:
    cur = conn.execute(
        """INSERT INTO attachments
           (note_id, file_path, file_size, mime_type, original_name, is_oversized)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (att.note_id, att.file_path, att.file_size, att.mime_type,
         att.original_name, int(att.is_oversized)),
    )
    conn.commit()
    return cur.lastrowid


def list_attachments(conn: sqlite3.Connection, note_id: int) -> list[Attachment]:
    cur = conn.execute(
        """SELECT id, note_id, file_path, file_size, mime_type, original_name, is_oversized
           FROM attachments WHERE note_id = ?""",
        (note_id,),
    )
    fields = "id note_id file_path file_size mime_type original_name is_oversized".split()
    out = []
    for row in cur.fetchall():
        d = dict(zip(fields, row))
        d["is_oversized"] = bool(d["is_oversized"])
        out.append(Attachment(**d))
    return out
```

- [ ] **Step 4: Run tests, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/core/attachments.py tests/test_attachments.py
git commit -m "feat(core): attachments repository"
```

---

### Task 7: Vector index helpers

**Files:**
- Create: `src/core/vec.py`
- Create: `tests/test_vec.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vec.py
import struct
from src.core.db import open_db, init_schema
from src.core.vec import upsert_embedding, search_similar

def _vec(values):
    return struct.pack(f"{len(values)}f", *values)

def test_upsert_and_search(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    e1 = [1.0] + [0.0] * 1023
    e2 = [0.0, 1.0] + [0.0] * 1022
    upsert_embedding(conn, note_id=1, embedding=e1)
    upsert_embedding(conn, note_id=2, embedding=e2)
    results = search_similar(conn, query_embedding=e1, limit=2)
    assert results[0][0] == 1
    assert len(results) == 2
```

- [ ] **Step 2: Run test, expect failure**

- [ ] **Step 3: Write `src/core/vec.py`**

```python
import sqlite3
import struct


def _serialize(embedding: list[float]) -> bytes:
    if len(embedding) != 1024:
        raise ValueError(f"expected 1024 dims, got {len(embedding)}")
    return struct.pack(f"{len(embedding)}f", *embedding)


def upsert_embedding(conn: sqlite3.Connection, note_id: int, embedding: list[float]) -> None:
    blob = _serialize(embedding)
    conn.execute("DELETE FROM notes_vec WHERE note_id = ?", (note_id,))
    conn.execute(
        "INSERT INTO notes_vec (note_id, embedding) VALUES (?, ?)",
        (note_id, blob),
    )
    conn.commit()


def search_similar(conn: sqlite3.Connection, query_embedding: list[float],
                   limit: int = 30) -> list[tuple[int, float]]:
    blob = _serialize(query_embedding)
    cur = conn.execute(
        """SELECT note_id, distance FROM notes_vec
           WHERE embedding MATCH ? AND k = ? ORDER BY distance""",
        (blob, limit),
    )
    return [(row[0], row[1]) for row in cur.fetchall()]
```

- [ ] **Step 4: Run tests, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/core/vec.py tests/test_vec.py
git commit -m "feat(core): vector index upsert/search helpers"
```

---

## Phase 3 — External adapters (key validation)

### Task 8: Settings loader from `.env`

**Files:**
- Create: `src/core/settings.py`
- Create: `tests/test_settings.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_settings.py
import os
from src.core.settings import load_settings

def test_load_settings(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234:abc")
    monkeypatch.setenv("OWNER_TELEGRAM_ID", "999")
    s = load_settings()
    assert s.telegram_bot_token == "1234:abc"
    assert s.owner_telegram_id == 999

def test_missing_env_raises(monkeypatch):
    import pytest
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("OWNER_TELEGRAM_ID", raising=False)
    with pytest.raises(RuntimeError):
        load_settings()
```

- [ ] **Step 2: Run test, expect failure**

- [ ] **Step 3: Write `src/core/settings.py`**

```python
import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    owner_telegram_id: int
    db_path: str


def load_settings() -> Settings:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    owner_str = os.environ.get("OWNER_TELEGRAM_ID", "").strip()
    if not token or not owner_str:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN and OWNER_TELEGRAM_ID must be set in .env"
        )
    return Settings(
        telegram_bot_token=token,
        owner_telegram_id=int(owner_str),
        db_path=os.environ.get("SOROKA_DB_PATH", "/app/data/soroka.db"),
    )
```

- [ ] **Step 4: Run tests, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/core/settings.py tests/test_settings.py
git commit -m "feat(core): settings loader from .env"
```

---

### Task 9: Jina adapter (embeddings + key validation)

**Files:**
- Create: `src/adapters/jina.py`
- Create: `tests/test_jina.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_jina.py
import pytest
from src.adapters.jina import JinaClient, JinaError

@pytest.mark.asyncio
async def test_validate_key_success(httpx_mock):
    httpx_mock.add_response(
        url="https://api.jina.ai/v1/embeddings",
        method="POST",
        json={"data": [{"embedding": [0.0] * 1024}]},
    )
    c = JinaClient(api_key="test")
    assert await c.validate_key() is True

@pytest.mark.asyncio
async def test_validate_key_unauthorized(httpx_mock):
    httpx_mock.add_response(
        url="https://api.jina.ai/v1/embeddings",
        method="POST",
        status_code=401,
        json={"error": "unauthorized"},
    )
    c = JinaClient(api_key="bad")
    assert await c.validate_key() is False

@pytest.mark.asyncio
async def test_embed_passage(httpx_mock):
    expected = [0.1] * 1024
    httpx_mock.add_response(
        url="https://api.jina.ai/v1/embeddings",
        json={"data": [{"embedding": expected}]},
    )
    c = JinaClient(api_key="test")
    out = await c.embed("hello", role="passage")
    assert out == expected
```

- [ ] **Step 2: Run test, expect failure**

- [ ] **Step 3: Write `src/adapters/jina.py`**

```python
from typing import Literal

import httpx


class JinaError(Exception):
    pass


class JinaClient:
    URL = "https://api.jina.ai/v1/embeddings"
    MODEL = "jina-embeddings-v3"

    def __init__(self, api_key: str, timeout: float = 30.0):
        self._api_key = api_key
        self._timeout = timeout

    async def validate_key(self) -> bool:
        try:
            await self.embed("ping", role="passage")
            return True
        except JinaError:
            return False

    async def embed(self, text: str, role: Literal["passage", "query"] = "passage") -> list[float]:
        task = "retrieval.passage" if role == "passage" else "retrieval.query"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                self.URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self.MODEL, "task": task, "input": [text]},
            )
        if r.status_code != 200:
            raise JinaError(f"{r.status_code}: {r.text[:200]}")
        return r.json()["data"][0]["embedding"]
```

- [ ] **Step 4: Run tests, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/adapters/jina.py tests/test_jina.py
git commit -m "feat(adapters): Jina embeddings client"
```

---

### Task 10: Deepgram adapter (transcription + key validation)

**Files:**
- Create: `src/adapters/deepgram.py`
- Create: `tests/test_deepgram.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_deepgram.py
import pytest
from src.adapters.deepgram import DeepgramClient

@pytest.mark.asyncio
async def test_validate_key_success(httpx_mock):
    httpx_mock.add_response(
        url="https://api.deepgram.com/v1/projects",
        json={"projects": []},
    )
    c = DeepgramClient(api_key="ok")
    assert await c.validate_key() is True

@pytest.mark.asyncio
async def test_transcribe_returns_text(httpx_mock):
    httpx_mock.add_response(
        url="https://api.deepgram.com/v1/listen?model=nova-3&language=multi&smart_format=true",
        json={"results": {"channels": [{"alternatives": [{"transcript": "привет мир"}]}]}},
    )
    c = DeepgramClient(api_key="ok")
    text = await c.transcribe(b"FAKE_AUDIO_BYTES", mime="audio/ogg")
    assert text == "привет мир"
```

- [ ] **Step 2: Run test, expect failure**

- [ ] **Step 3: Write `src/adapters/deepgram.py`**

```python
import httpx


class DeepgramError(Exception):
    pass


class DeepgramClient:
    BASE = "https://api.deepgram.com/v1"
    MODEL = "nova-3"

    def __init__(self, api_key: str, timeout: float = 60.0):
        self._api_key = api_key
        self._timeout = timeout

    async def validate_key(self) -> bool:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(
                f"{self.BASE}/projects",
                headers={"Authorization": f"Token {self._api_key}"},
            )
        return r.status_code == 200

    async def transcribe(self, audio_bytes: bytes, mime: str = "audio/ogg") -> str:
        params = {"model": self.MODEL, "language": "multi", "smart_format": "true"}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self.BASE}/listen",
                params=params,
                headers={
                    "Authorization": f"Token {self._api_key}",
                    "Content-Type": mime,
                },
                content=audio_bytes,
            )
        if r.status_code != 200:
            raise DeepgramError(f"{r.status_code}: {r.text[:200]}")
        data = r.json()
        try:
            return data["results"]["channels"][0]["alternatives"][0]["transcript"]
        except (KeyError, IndexError) as e:
            raise DeepgramError(f"unexpected response: {e}") from e
```

- [ ] **Step 4: Run tests, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/adapters/deepgram.py tests/test_deepgram.py
git commit -m "feat(adapters): Deepgram transcription client"
```

---

### Task 11: OpenRouter adapter (validate, list models, complete with fallback)

**Files:**
- Create: `src/adapters/openrouter.py`
- Create: `tests/test_openrouter.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_openrouter.py
import pytest
from src.adapters.openrouter import OpenRouterClient, ModelInfo

@pytest.mark.asyncio
async def test_validate_key_success(httpx_mock):
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/auth/key",
        json={"data": {"limit": 1.0}},
    )
    c = OpenRouterClient(api_key="ok")
    assert await c.validate_key() is True

@pytest.mark.asyncio
async def test_list_models_sorts_free_first(httpx_mock):
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/models",
        json={"data": [
            {"id": "anthropic/claude-3.5-haiku", "name": "Haiku",
             "pricing": {"prompt": "0.0000008", "completion": "0.000004"},
             "context_length": 200000},
            {"id": "google/gemini-2.0-flash-exp:free", "name": "Gemini Free",
             "pricing": {"prompt": "0", "completion": "0"},
             "context_length": 1000000},
            {"id": "meta-llama/llama-3.3-70b", "name": "Llama 3.3",
             "pricing": {"prompt": "0.00000059", "completion": "0.00000079"},
             "context_length": 131072},
        ]},
    )
    c = OpenRouterClient(api_key="ok")
    models = await c.list_models()
    assert models[0].id.endswith(":free")
    assert [m.id for m in models[1:]] == [
        "meta-llama/llama-3.3-70b",
        "anthropic/claude-3.5-haiku",
    ]

@pytest.mark.asyncio
async def test_complete_falls_back_on_primary_error(httpx_mock):
    # First call (primary) returns 503
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        match_json={"model": "primary/x", "messages": [{"role": "user", "content": "hi"}]},
        status_code=503,
        json={"error": "down"},
    )
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        match_json={"model": "fallback/y", "messages": [{"role": "user", "content": "hi"}]},
        json={"choices": [{"message": {"content": "ok"}}]},
    )
    c = OpenRouterClient(api_key="k")
    out = await c.complete(
        primary="primary/x", fallback="fallback/y",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert out == "ok"
```

- [ ] **Step 2: Run test, expect failure**

- [ ] **Step 3: Write `src/adapters/openrouter.py`**

```python
from dataclasses import dataclass
from typing import Optional

import httpx


class OpenRouterError(Exception):
    pass


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    prompt_price: float       # USD per token (prompt)
    completion_price: float   # USD per token (completion)
    context_length: int
    is_free: bool


class OpenRouterClient:
    BASE = "https://openrouter.ai/api/v1"
    HTTP_RETRY_STATUSES = {429, 500, 502, 503, 504}

    def __init__(self, api_key: str, timeout: float = 60.0):
        self._api_key = api_key
        self._timeout = timeout

    async def validate_key(self) -> bool:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(
                f"{self.BASE}/auth/key",
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        return r.status_code == 200

    async def list_models(self) -> list[ModelInfo]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(f"{self.BASE}/models")
        if r.status_code != 200:
            raise OpenRouterError(f"{r.status_code}: {r.text[:200]}")
        models = []
        for d in r.json()["data"]:
            try:
                prompt = float(d["pricing"]["prompt"])
                completion = float(d["pricing"]["completion"])
            except (KeyError, ValueError, TypeError):
                continue
            models.append(ModelInfo(
                id=d["id"],
                name=d.get("name", d["id"]),
                prompt_price=prompt,
                completion_price=completion,
                context_length=d.get("context_length", 0) or 0,
                is_free=d["id"].endswith(":free") or prompt == 0,
            ))
        return sorted(models, key=lambda m: (not m.is_free, m.prompt_price))

    async def complete(self, primary: str, fallback: Optional[str],
                       messages: list[dict], max_tokens: int = 1000) -> str:
        try:
            return await self._call(primary, messages, max_tokens)
        except OpenRouterError:
            if not fallback:
                raise
            return await self._call(fallback, messages, max_tokens)

    async def _call(self, model: str, messages: list[dict], max_tokens: int) -> str:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self.BASE}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": model, "messages": messages, "max_tokens": max_tokens},
            )
        if r.status_code in self.HTTP_RETRY_STATUSES or r.status_code >= 500:
            raise OpenRouterError(f"{r.status_code}: {r.text[:200]}")
        if r.status_code != 200:
            raise OpenRouterError(f"{r.status_code}: {r.text[:200]}")
        return r.json()["choices"][0]["message"]["content"]
```

- [ ] **Step 4: Run tests, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/adapters/openrouter.py tests/test_openrouter.py
git commit -m "feat(adapters): OpenRouter client (validate/list/complete with fallback)"
```

---

### Task 12: Telegram file downloader with size guard

**Files:**
- Create: `src/adapters/tg_files.py`
- Create: `tests/test_tg_files.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tg_files.py
import pytest
from src.adapters.tg_files import is_oversized, MAX_DOWNLOAD_BYTES

def test_is_oversized_threshold():
    assert is_oversized(MAX_DOWNLOAD_BYTES + 1)
    assert not is_oversized(MAX_DOWNLOAD_BYTES)
    assert not is_oversized(0)
```

- [ ] **Step 2: Run test, expect failure**

- [ ] **Step 3: Write `src/adapters/tg_files.py`**

```python
from pathlib import Path

# Telegram bot API allows downloading files up to 20 MB.
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024


def is_oversized(file_size: int) -> bool:
    return file_size > MAX_DOWNLOAD_BYTES


async def download_to_path(file, dest: Path) -> Path:
    """Wrapper around python-telegram-bot's File.download_to_drive.

    `file` is a telegram.File object obtained via context.bot.get_file().
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    await file.download_to_drive(custom_path=str(dest))
    return dest
```

- [ ] **Step 4: Run tests, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/adapters/tg_files.py tests/test_tg_files.py
git commit -m "feat(adapters): Telegram file size guard and download helper"
```

---

## Phase 4 — Bot skeleton & setup wizard

### Task 13: Bot main (polling, dispatcher, owner check)

**Files:**
- Create: `src/bot/main.py`
- Create: `src/bot/auth.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write the failing test for auth**

```python
# tests/test_auth.py
from src.bot.auth import is_owner

def test_is_owner_match():
    assert is_owner(user_id=42, owner_id=42)

def test_is_owner_mismatch():
    assert not is_owner(user_id=43, owner_id=42)
```

- [ ] **Step 2: Run test, expect failure**

- [ ] **Step 3: Write `src/bot/auth.py`**

```python
def is_owner(user_id: int, owner_id: int) -> bool:
    return user_id == owner_id
```

- [ ] **Step 4: Run test to verify pass**

- [ ] **Step 5: Write `src/bot/main.py`**

```python
import logging

from telegram.ext import Application, ApplicationBuilder

from src.core.db import open_db, init_schema
from src.core.settings import load_settings
from src.bot.handlers.commands import register_command_handlers
from src.bot.handlers.setup import register_setup_handlers
from src.bot.handlers.channel import register_channel_handlers
from src.bot.handlers.search import register_search_handlers


def build_app(settings, conn) -> Application:
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.bot_data["settings"] = settings
    app.bot_data["conn"] = conn

    register_setup_handlers(app)
    register_command_handlers(app)
    register_channel_handlers(app)
    register_search_handlers(app)
    return app


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = load_settings()
    conn = open_db(settings.db_path)
    init_schema(conn)
    app = build_app(settings, conn)
    app.run_polling()


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Commit**

```bash
git add src/bot/main.py src/bot/auth.py tests/test_auth.py
git commit -m "feat(bot): main entry, auth, application skeleton"
```

---

### Task 14: Reactions utility

**Files:**
- Create: `src/bot/handlers/reactions.py`

- [ ] **Step 1: Write `src/bot/handlers/reactions.py`**

```python
from telegram import Bot, ReactionTypeEmoji

PROCESSING = "🔄"
SUCCESS = "✅"
FAILURE = "❌"
OVERSIZED = "⚠️"


async def set_reaction(bot: Bot, chat_id: int, message_id: int, emoji: str) -> None:
    try:
        await bot.set_message_reaction(
            chat_id=chat_id,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji=emoji)],
        )
    except Exception:
        # Reactions are best-effort; never fail ingestion because of them.
        pass


async def clear_reaction(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.set_message_reaction(
            chat_id=chat_id, message_id=message_id, reaction=[],
        )
    except Exception:
        pass
```

- [ ] **Step 2: Commit**

```bash
git add src/bot/handlers/reactions.py
git commit -m "feat(bot): reactions utility (processing/success/failure/oversized)"
```

---

### Task 15: Setup wizard step 1 — Jina key

**Files:**
- Create: `src/bot/handlers/setup.py`
- Create: `tests/test_setup_wizard.py`

- [ ] **Step 1: Write the failing test for the state machine**

```python
# tests/test_setup_wizard.py
import pytest
from unittest.mock import AsyncMock, patch

from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner, get_owner
from src.bot.handlers.setup import process_setup_message

@pytest.mark.asyncio
async def test_jina_step_accepts_valid_key(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    # advance to jina step
    from src.core.owners import advance_setup_step
    advance_setup_step(conn, 1, "jina")

    with patch("src.bot.handlers.setup.JinaClient") as mock_cls:
        mock_cls.return_value.validate_key = AsyncMock(return_value=True)
        next_prompt = await process_setup_message(conn, owner_id=1, text="jina-key-123")

    assert "Шаг 2" in next_prompt or "Deepgram" in next_prompt
    assert get_owner(conn, 1).jina_api_key == "jina-key-123"
    assert get_owner(conn, 1).setup_step == "deepgram"

@pytest.mark.asyncio
async def test_jina_step_rejects_invalid_key(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    from src.core.owners import advance_setup_step
    advance_setup_step(conn, 1, "jina")

    with patch("src.bot.handlers.setup.JinaClient") as mock_cls:
        mock_cls.return_value.validate_key = AsyncMock(return_value=False)
        msg = await process_setup_message(conn, owner_id=1, text="bad-key")

    assert "не подошёл" in msg.lower() or "invalid" in msg.lower()
    assert get_owner(conn, 1).jina_api_key is None
    assert get_owner(conn, 1).setup_step == "jina"
```

- [ ] **Step 2: Run test, expect failure**

- [ ] **Step 3: Write skeleton of `src/bot/handlers/setup.py`**

```python
import sqlite3
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
)

from src.adapters.jina import JinaClient
from src.adapters.deepgram import DeepgramClient
from src.adapters.openrouter import OpenRouterClient
from src.core.owners import (
    create_or_get_owner, get_owner, update_owner_field, advance_setup_step,
)
from src.bot.auth import is_owner

PROMPTS = {
    "jina":      "Шаг 1/6 — ключ Jina.\nЗайди на jina.ai → API → Free tier.\nПришли ключ сообщением.",
    "deepgram":  "Шаг 2/6 — ключ Deepgram.\nЗайди на deepgram.com, создай API key.\nПришли ключ сообщением.",
    "openrouter":"Шаг 3/6 — ключ OpenRouter.\nЗайди на openrouter.ai/keys.\nПришли ключ сообщением.",
    "models":    "Шаг 4/6 — выбор моделей. Сейчас покажу список — нажимай кнопки.",
    "github":    ("Шаг 5/6 — резервное копирование на GitHub.\n"
                  "1) Создай **приватный** репозиторий вида `username/soroka-data` на github.com/new\n"
                  "2) Сгенерируй Personal Access Token на github.com/settings/tokens/new с правами `repo`\n"
                  "3) Пришли одной строкой: `ghp_xxx username/soroka-data`\n"
                  "Чтобы пропустить (не рекомендую) — /skip"),
    "channel":   ("Шаг 6/6 — канал-инбокс.\n"
                  "Создай **приватный** канал «Избранное 2», добавь меня админом\n"
                  "(права `Post Messages` + `Add Reactions`),\n"
                  "затем форварднь сюда любое сообщение из этого канала."),
}

DONE_MESSAGE = (
    "Готово! Поехали.\n"
    "• /help — справка\n"
    "• /status — текущие настройки\n"
    "• /export — экспорт базы\n"
    "• /mcp — конфиг для Claude Desktop\n"
    "Кидай в канал что угодно — я индексирую. Ищи прямо здесь, в DM."
)


async def process_setup_message(conn: sqlite3.Connection, owner_id: int,
                                 text: str) -> str:
    """Pure logic of the setup wizard. Returns the next prompt to send."""
    owner = get_owner(conn, owner_id)
    step = owner.setup_step or "jina"

    if step == "jina":
        client = JinaClient(api_key=text.strip())
        if not await client.validate_key():
            return "Ключ Jina не подошёл. Попробуй ещё раз."
        update_owner_field(conn, owner_id, "jina_api_key", text.strip())
        advance_setup_step(conn, owner_id, "deepgram")
        return PROMPTS["deepgram"]

    if step == "deepgram":
        client = DeepgramClient(api_key=text.strip())
        if not await client.validate_key():
            return "Ключ Deepgram не подошёл. Попробуй ещё раз."
        update_owner_field(conn, owner_id, "deepgram_api_key", text.strip())
        advance_setup_step(conn, owner_id, "openrouter")
        return PROMPTS["openrouter"]

    if step == "openrouter":
        client = OpenRouterClient(api_key=text.strip())
        if not await client.validate_key():
            return "Ключ OpenRouter не подошёл. Попробуй ещё раз."
        update_owner_field(conn, owner_id, "openrouter_key", text.strip())
        advance_setup_step(conn, owner_id, "models")
        return "Ключ принят. Сейчас покажу список моделей — отправь /models."

    if step == "github":
        # Parsed in Task 17 (github step handler)
        from src.bot.handlers.setup_github import handle_github_step
        return await handle_github_step(conn, owner_id, text)

    if step == "channel":
        # Set via forward handler — see Task 18
        return "Жду форвард сообщения из канала «Избранное 2»."

    if step == "done" or step == "models":
        return ""  # ignore — handled by other handlers

    return "Не понимаю. Попробуй /start."


async def start_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]

    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        await update.message.reply_text("Бот настроен на одного владельца.")
        return

    create_or_get_owner(conn, telegram_id=settings.owner_telegram_id)
    owner = get_owner(conn, settings.owner_telegram_id)

    if owner.setup_step == "done":
        await update.message.reply_text(DONE_MESSAGE)
        return

    if owner.setup_step is None:
        advance_setup_step(conn, settings.owner_telegram_id, "jina")
        owner = get_owner(conn, settings.owner_telegram_id)

    await update.message.reply_text(
        "Привет! Я Soroka. Настроим за 5 минут.\n\n" + PROMPTS[owner.setup_step]
    )


def register_setup_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start_handler))
    # Catch-all DM text handler is wired in Task 19 (search) — setup state takes priority there.
```

- [ ] **Step 4: Run wizard test, expect PASS**

Run: `pytest tests/test_setup_wizard.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/bot/handlers/setup.py tests/test_setup_wizard.py
git commit -m "feat(bot): setup wizard core state machine (jina/deepgram/openrouter steps)"
```

---

### Task 16: Setup wizard step 4 — model picker (inline keyboard)

**Files:**
- Create: `src/bot/handlers/setup_models.py`
- Modify: `src/bot/handlers/setup.py` to call into model handlers

- [ ] **Step 1: Write `src/bot/handlers/setup_models.py`**

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from src.adapters.openrouter import OpenRouterClient
from src.core.owners import get_owner, update_owner_field, advance_setup_step

PAGE_SIZE = 5


def _format_button(m) -> str:
    if m.is_free:
        prefix = "🆓"
        price = "free"
    else:
        prefix = " "
        price = f"${m.prompt_price * 1_000_000:.2f}/M"
    return f"{prefix} {price}  {m.id[:40]}"


def _keyboard(models: list, page: int, role: str) -> InlineKeyboardMarkup:
    start = page * PAGE_SIZE
    chunk = models[start:start + PAGE_SIZE]
    rows = [
        [InlineKeyboardButton(_format_button(m), callback_data=f"pick:{role}:{m.id}")]
        for m in chunk
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"page:{role}:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{(len(models)-1)//PAGE_SIZE + 1}",
                                    callback_data="noop"))
    if start + PAGE_SIZE < len(models):
        nav.append(InlineKeyboardButton("▶️", callback_data=f"page:{role}:{page+1}"))
    rows.append(nav)
    return InlineKeyboardMarkup(rows)


async def models_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    owner = get_owner(conn, settings.owner_telegram_id)
    if not owner or not owner.openrouter_key:
        await update.message.reply_text("Сначала настрой ключ OpenRouter (/start).")
        return

    client = OpenRouterClient(api_key=owner.openrouter_key)
    models = await client.list_models()
    ctx.application.bot_data["model_list"] = models

    role = "primary" if not owner.primary_model else "fallback"
    label = "основную" if role == "primary" else "fallback"
    await update.message.reply_text(
        f"Выбери {label} модель:",
        reply_markup=_keyboard(models, 0, role),
    )


async def model_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "noop":
        return

    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    models = ctx.application.bot_data.get("model_list", [])

    if data.startswith("page:"):
        _, role, page_str = data.split(":")
        await query.edit_message_reply_markup(
            reply_markup=_keyboard(models, int(page_str), role),
        )
        return

    if data.startswith("pick:"):
        _, role, model_id = data.split(":", 2)
        field = "primary_model" if role == "primary" else "fallback_model"
        update_owner_field(conn, settings.owner_telegram_id, field, model_id)
        await query.edit_message_text(f"✓ {role}: {model_id}")

        owner = get_owner(conn, settings.owner_telegram_id)
        if role == "primary":
            await query.message.reply_text(
                "Теперь выбери fallback (на случай если основная упадёт):",
                reply_markup=_keyboard(models, 0, "fallback"),
            )
        else:
            # both selected
            if owner.setup_step == "models":
                advance_setup_step(conn, settings.owner_telegram_id, "github")
                from src.bot.handlers.setup import PROMPTS
                await query.message.reply_text(PROMPTS["github"])


def register_model_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("models", models_command))
    app.add_handler(CallbackQueryHandler(model_callback, pattern=r"^(pick|page|noop):"))
```

- [ ] **Step 2: Wire into `register_setup_handlers`**

Edit `src/bot/handlers/setup.py` `register_setup_handlers` to also call `register_model_handlers`:

```python
from src.bot.handlers.setup_models import register_model_handlers

def register_setup_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start_handler))
    register_model_handlers(app)
```

- [ ] **Step 3: Smoke test (manual TODO list — no automated test for inline keyboards):**
- ensure `register_model_handlers` is registered without errors via `pytest -k "test_main_imports"`

Add `tests/test_main_imports.py`:

```python
def test_imports_compose():
    from src.bot.main import build_app  # noqa
```

- [ ] **Step 4: Commit**

```bash
git add src/bot/handlers/setup_models.py src/bot/handlers/setup.py tests/test_main_imports.py
git commit -m "feat(bot): model picker with inline keyboard pagination"
```

---

### Task 17: Setup wizard step 5 — GitHub mirror

**Files:**
- Create: `src/bot/handlers/setup_github.py`
- Create: `src/adapters/github_mirror.py`
- Create: `tests/test_github_mirror.py`

- [ ] **Step 1: Write the failing test for the adapter**

```python
# tests/test_github_mirror.py
import pytest
from src.adapters.github_mirror import GitHubMirror, GitHubMirrorError

@pytest.mark.asyncio
async def test_validate_repo_success(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/me/soroka-data",
        json={"name": "soroka-data", "private": True},
    )
    m = GitHubMirror(token="t", repo="me/soroka-data")
    assert await m.validate() is True

@pytest.mark.asyncio
async def test_validate_repo_public_fails(httpx_mock):
    httpx_mock.add_response(
        url="https://api.github.com/repos/me/soroka-data",
        json={"name": "soroka-data", "private": False},
    )
    m = GitHubMirror(token="t", repo="me/soroka-data")
    with pytest.raises(GitHubMirrorError, match="private"):
        await m.validate()
```

- [ ] **Step 2: Write `src/adapters/github_mirror.py`**

```python
from pathlib import Path
import httpx


class GitHubMirrorError(Exception):
    pass


class GitHubMirror:
    BASE = "https://api.github.com"

    def __init__(self, token: str, repo: str, timeout: float = 60.0):
        self._token = token
        self._repo = repo
        self._timeout = timeout

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def validate(self) -> bool:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(f"{self.BASE}/repos/{self._repo}", headers=self._headers)
        if r.status_code == 401:
            raise GitHubMirrorError("token unauthorized")
        if r.status_code == 404:
            raise GitHubMirrorError("repo not found or token has no access")
        if r.status_code != 200:
            raise GitHubMirrorError(f"{r.status_code}: {r.text[:200]}")
        if not r.json().get("private", False):
            raise GitHubMirrorError("repo must be private")
        return True

    async def upload_release(self, tag: str, title: str, body: str, asset: Path) -> str:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self.BASE}/repos/{self._repo}/releases",
                headers=self._headers,
                json={"tag_name": tag, "name": title, "body": body},
            )
            if r.status_code not in (200, 201):
                raise GitHubMirrorError(f"create release: {r.status_code} {r.text[:200]}")
            release = r.json()
            upload_url = release["upload_url"].split("{")[0]

            with asset.open("rb") as f:
                r2 = await client.post(
                    f"{upload_url}?name={asset.name}",
                    headers={**self._headers, "Content-Type": "application/octet-stream"},
                    content=f.read(),
                )
            if r2.status_code not in (200, 201):
                raise GitHubMirrorError(f"upload asset: {r2.status_code} {r2.text[:200]}")
            return r2.json()["browser_download_url"]
```

- [ ] **Step 3: Write `src/bot/handlers/setup_github.py`**

```python
import sqlite3

from src.adapters.github_mirror import GitHubMirror, GitHubMirrorError
from src.core.owners import update_owner_field, advance_setup_step


async def handle_github_step(conn: sqlite3.Connection, owner_id: int, text: str) -> str:
    parts = text.strip().split()
    if len(parts) != 2 or "/" not in parts[1]:
        return ("Не понял. Пришли одной строкой: `<token> <user>/<repo>`\n"
                "Например: `ghp_xxxx me/soroka-data`")
    token, repo = parts
    mirror = GitHubMirror(token=token, repo=repo)
    try:
        await mirror.validate()
    except GitHubMirrorError as e:
        return f"GitHub отверг настройки: {e}. Попробуй ещё раз."

    update_owner_field(conn, owner_id, "github_token", token)
    update_owner_field(conn, owner_id, "github_mirror_repo", repo)
    advance_setup_step(conn, owner_id, "channel")
    from src.bot.handlers.setup import PROMPTS
    return "✓ GitHub-зеркало подключено.\n\n" + PROMPTS["channel"]


async def handle_skip_github(conn: sqlite3.Connection, owner_id: int) -> str:
    advance_setup_step(conn, owner_id, "channel")
    from src.bot.handlers.setup import PROMPTS
    return ("⚠ Без зеркала /export не сможет отдавать большие архивы.\n\n"
            + PROMPTS["channel"])
```

- [ ] **Step 4: Run tests, expect PASS**

Run: `pytest tests/test_github_mirror.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/adapters/github_mirror.py src/bot/handlers/setup_github.py tests/test_github_mirror.py
git commit -m "feat(bot): GitHub mirror adapter and setup wizard step 5"
```

---

### Task 18: Setup wizard step 6 — channel inbox

**Files:**
- Modify: `src/bot/handlers/setup.py` to handle forwards as inbox bind

- [ ] **Step 1: Add forward handler**

In `src/bot/handlers/setup.py`, add at the top:

```python
from telegram.ext import MessageHandler, filters
```

Then add a handler function:

```python
async def forward_inbox_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return

    owner = get_owner(conn, settings.owner_telegram_id)
    if owner.setup_step != "channel":
        return  # other handlers (search) take over

    msg = update.message
    if not msg.forward_origin or msg.forward_origin.type != "channel":
        await msg.reply_text("Это не форвард из канала. Форвардни сообщение прямо из канала «Избранное 2».")
        return

    chat_id = msg.forward_origin.chat.id
    update_owner_field(conn, settings.owner_telegram_id, "inbox_chat_id", chat_id)
    advance_setup_step(conn, settings.owner_telegram_id, "done")

    # Test publish into the channel
    try:
        sent = await ctx.bot.send_message(
            chat_id=chat_id,
            text="✅ Soroka подключилась.",
        )
        # Schedule deletion after 10s — best-effort
        ctx.job_queue.run_once(
            lambda c: c.bot.delete_message(chat_id, sent.message_id),
            when=10,
        )
    except Exception:
        await msg.reply_text("⚠ Не могу публиковать в канал. Проверь права админа.")
        return

    await msg.reply_text(DONE_MESSAGE)


async def skip_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    owner = get_owner(conn, settings.owner_telegram_id)
    if owner and owner.setup_step == "github":
        from src.bot.handlers.setup_github import handle_skip_github
        msg = await handle_skip_github(conn, settings.owner_telegram_id)
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text("Сейчас нечего пропускать.")
```

Update `register_setup_handlers`:

```python
def register_setup_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("skip", skip_handler))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.FORWARDED,
        forward_inbox_handler,
    ))
    register_model_handlers(app)
```

- [ ] **Step 2: Smoke-test imports**

Run: `pytest tests/test_main_imports.py`

- [ ] **Step 3: Commit**

```bash
git add src/bot/handlers/setup.py
git commit -m "feat(bot): setup wizard step 6 (channel inbox via forward)"
```

---

## Phase 5 — Extractors

### Task 19: Text & caption extractor (no-op)

**Files:**
- Create: `src/adapters/extractors/plain.py`
- Create: `tests/test_extractor_plain.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extractor_plain.py
from src.adapters.extractors.plain import extract_text

def test_extract_text_returns_input():
    assert extract_text("hello") == "hello"
    assert extract_text("  trimmed  ") == "trimmed"
    assert extract_text(None) == ""
```

- [ ] **Step 2: Run test, expect failure**

- [ ] **Step 3: Write `src/adapters/extractors/plain.py`**

```python
def extract_text(text: str | None) -> str:
    if not text:
        return ""
    return text.strip()
```

- [ ] **Step 4: Run, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/adapters/extractors/plain.py tests/test_extractor_plain.py
git commit -m "feat(extractors): plain text passthrough"
```

---

### Task 20: Web URL extractor (trafilatura)

**Files:**
- Create: `src/adapters/extractors/web.py`
- Create: `tests/test_extractor_web.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extractor_web.py
from src.adapters.extractors.web import is_url, extract_web

def test_is_url_basic():
    assert is_url("https://example.com")
    assert is_url("http://x.org/a/b")
    assert not is_url("hello")
    assert not is_url("file://etc/passwd")  # only http(s)

def test_extract_web_uses_trafilatura(monkeypatch):
    monkeypatch.setattr(
        "src.adapters.extractors.web.trafilatura.fetch_url",
        lambda url, **kw: "<html><body><p>article body</p></body></html>",
    )
    monkeypatch.setattr(
        "src.adapters.extractors.web.trafilatura.extract",
        lambda html, **kw: "article body",
    )
    title, text = extract_web("https://example.com/x")
    assert "article body" in text
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Write `src/adapters/extractors/web.py`**

```python
import re
import trafilatura

URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def is_url(text: str) -> bool:
    return bool(URL_RE.match(text.strip()))


def extract_web(url: str) -> tuple[str | None, str]:
    """Returns (title, body_text)."""
    html = trafilatura.fetch_url(url)
    if not html:
        return None, ""
    text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    metadata = trafilatura.extract_metadata(html)
    title = metadata.title if metadata else None
    return title, text
```

- [ ] **Step 4: Run, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/adapters/extractors/web.py tests/test_extractor_web.py
git commit -m "feat(extractors): web pages via trafilatura"
```

---

### Task 21: YouTube extractor (yt-dlp)

**Files:**
- Create: `src/adapters/extractors/youtube.py`
- Create: `tests/test_extractor_youtube.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extractor_youtube.py
from src.adapters.extractors.youtube import is_youtube_url

def test_is_youtube_url_variations():
    assert is_youtube_url("https://www.youtube.com/watch?v=abc")
    assert is_youtube_url("https://youtu.be/abc")
    assert is_youtube_url("https://m.youtube.com/watch?v=abc")
    assert not is_youtube_url("https://example.com/watch?v=abc")
```

- [ ] **Step 2: Write `src/adapters/extractors/youtube.py`**

```python
import re
import tempfile
from pathlib import Path

YT_RE = re.compile(
    r"^https?://(?:www\.|m\.)?(?:youtube\.com/watch\?v=|youtu\.be/)",
    re.IGNORECASE,
)


def is_youtube_url(text: str) -> bool:
    return bool(YT_RE.match(text.strip()))


def extract_youtube(url: str) -> tuple[str | None, str]:
    """Returns (title, transcript_or_description). Uses auto-subs if available."""
    import yt_dlp

    with tempfile.TemporaryDirectory() as td:
        opts = {
            "skip_download": True,
            "writeautomaticsub": True,
            "subtitleslangs": ["ru", "en"],
            "subtitlesformat": "vtt",
            "outtmpl": str(Path(td) / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title")
            description = info.get("description") or ""
            video_id = info.get("id")

            ydl.process_info(info)

        for ext in ("vtt", "srt"):
            for lang in ("ru", "en"):
                p = Path(td) / f"{video_id}.{lang}.{ext}"
                if p.exists():
                    return title, _vtt_to_text(p.read_text(encoding="utf-8"))

    return title, description


def _vtt_to_text(vtt: str) -> str:
    lines = []
    for line in vtt.splitlines():
        s = line.strip()
        if not s or s.startswith(("WEBVTT", "NOTE")) or "-->" in s:
            continue
        if s.replace(":", "").replace(".", "").isdigit():
            continue
        lines.append(s)
    return "\n".join(lines)
```

- [ ] **Step 3: Run, expect PASS**

- [ ] **Step 4: Commit**

```bash
git add src/adapters/extractors/youtube.py tests/test_extractor_youtube.py
git commit -m "feat(extractors): YouTube via yt-dlp (auto-subs, fallback to description)"
```

---

### Task 22: PDF extractor

**Files:**
- Create: `src/adapters/extractors/pdf.py`
- Create: `tests/test_extractor_pdf.py`
- Create: `tests/fixtures/sample.pdf` (a tiny generated PDF)

- [ ] **Step 1: Generate a fixture PDF**

Add a one-shot fixture builder in `tests/conftest.py`:

```python
import pytest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def ensure_fixture_pdf():
    FIXTURES.mkdir(exist_ok=True)
    pdf_path = FIXTURES / "sample.pdf"
    if pdf_path.exists():
        return
    from pypdf import PdfWriter
    from pypdf.generic import RectangleObject
    # Minimal one-page PDF with embedded text via ReportLab fallback
    try:
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(str(pdf_path))
        c.drawString(100, 750, "Hello PDF world from Soroka")
        c.save()
    except ImportError:
        # ReportLab is dev-only; install if missing
        import subprocess, sys
        subprocess.run([sys.executable, "-m", "pip", "install", "reportlab"], check=True)
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(str(pdf_path))
        c.drawString(100, 750, "Hello PDF world from Soroka")
        c.save()
```

Add `reportlab` to the `dev` extras in `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = [
    ...,
    "reportlab==4.*",
]
```

- [ ] **Step 2: Write the test**

```python
# tests/test_extractor_pdf.py
from pathlib import Path
from src.adapters.extractors.pdf import extract_pdf


def test_extract_pdf(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "sample.pdf"
    text = extract_pdf(fixture)
    assert "Hello PDF world from Soroka" in text
```

- [ ] **Step 3: Write `src/adapters/extractors/pdf.py`**

```python
from pathlib import Path
from pypdf import PdfReader


def extract_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(p.strip() for p in parts if p.strip())
```

- [ ] **Step 4: Run, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/adapters/extractors/pdf.py tests/test_extractor_pdf.py tests/conftest.py pyproject.toml
git commit -m "feat(extractors): PDF text via pypdf"
```

---

### Task 23: DOCX extractor

**Files:**
- Create: `src/adapters/extractors/docx.py`
- Create: `tests/test_extractor_docx.py`

- [ ] **Step 1: Write the test (with fixture builder)**

```python
# tests/test_extractor_docx.py
from pathlib import Path
from docx import Document
from src.adapters.extractors.docx import extract_docx


def test_extract_docx(tmp_path):
    p = tmp_path / "x.docx"
    d = Document()
    d.add_paragraph("Первый абзац")
    d.add_paragraph("Второй абзац")
    d.save(p)
    text = extract_docx(p)
    assert "Первый абзац" in text
    assert "Второй абзац" in text
```

- [ ] **Step 2: Write `src/adapters/extractors/docx.py`**

```python
from pathlib import Path
from docx import Document


def extract_docx(path: Path) -> str:
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
```

- [ ] **Step 3: Run, PASS**

- [ ] **Step 4: Commit**

```bash
git add src/adapters/extractors/docx.py tests/test_extractor_docx.py
git commit -m "feat(extractors): DOCX text via python-docx"
```

---

### Task 24: XLSX extractor

**Files:**
- Create: `src/adapters/extractors/xlsx.py`
- Create: `tests/test_extractor_xlsx.py`

- [ ] **Step 1: Write the test**

```python
# tests/test_extractor_xlsx.py
from pathlib import Path
from openpyxl import Workbook
from src.adapters.extractors.xlsx import extract_xlsx


def test_extract_xlsx(tmp_path):
    p = tmp_path / "x.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws["A1"] = "Имя"
    ws["B1"] = "Возраст"
    ws["A2"] = "Андрей"
    ws["B2"] = 35
    wb.save(p)
    text = extract_xlsx(p)
    assert "Имя" in text
    assert "Андрей" in text
    assert "35" in text
```

- [ ] **Step 2: Write `src/adapters/extractors/xlsx.py`**

```python
from pathlib import Path
from openpyxl import load_workbook


def extract_xlsx(path: Path) -> str:
    wb = load_workbook(str(path), data_only=True, read_only=True)
    parts = []
    for sheet in wb.worksheets:
        parts.append(f"# {sheet.title}")
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c) if c is not None else "" for c in row]
            if any(cells):
                parts.append("\t".join(cells))
    wb.close()
    return "\n".join(parts)
```

- [ ] **Step 3: Run, PASS**

- [ ] **Step 4: Commit**

```bash
git add src/adapters/extractors/xlsx.py tests/test_extractor_xlsx.py
git commit -m "feat(extractors): XLSX text via openpyxl"
```

---

### Task 25: OCR extractor (tesseract)

**Files:**
- Create: `src/adapters/extractors/ocr.py`
- Create: `tests/test_extractor_ocr.py`

- [ ] **Step 1: Write `src/adapters/extractors/ocr.py`**

```python
from pathlib import Path
import pytesseract
from PIL import Image


def extract_ocr(path: Path, lang: str = "rus+eng") -> str:
    img = Image.open(str(path))
    return pytesseract.image_to_string(img, lang=lang).strip()
```

- [ ] **Step 2: Write a smoke test that gates on tesseract availability**

```python
# tests/test_extractor_ocr.py
import pytest
import shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from src.adapters.extractors.ocr import extract_ocr


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_extract_ocr(tmp_path):
    img_path = tmp_path / "x.png"
    img = Image.new("RGB", (400, 80), "white")
    draw = ImageDraw.Draw(img)
    # Use default font; result is OK enough to recognize ASCII
    draw.text((10, 20), "Hello OCR", fill="black")
    img.save(img_path)

    text = extract_ocr(img_path, lang="eng")
    assert "Hello" in text or "OCR" in text
```

- [ ] **Step 3: Run, PASS (or SKIP if tesseract missing locally)**

- [ ] **Step 4: Commit**

```bash
git add src/adapters/extractors/ocr.py tests/test_extractor_ocr.py
git commit -m "feat(extractors): OCR via tesseract (rus+eng)"
```

---

### Task 26: Kind detection (router)

**Files:**
- Create: `src/core/kind.py`
- Create: `tests/test_kind.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kind.py
from src.core.kind import detect_kind_from_text, detect_kind_from_message

def test_detect_text():
    assert detect_kind_from_text("just thinking aloud") == "text"

def test_detect_youtube():
    assert detect_kind_from_text("https://youtu.be/dQw4w9WgXcQ") == "youtube"

def test_detect_web():
    assert detect_kind_from_text("https://example.com/article") == "web"
```

- [ ] **Step 2: Write `src/core/kind.py`**

```python
from src.adapters.extractors.web import is_url
from src.adapters.extractors.youtube import is_youtube_url


def detect_kind_from_text(text: str) -> str:
    s = text.strip()
    if is_youtube_url(s):
        return "youtube"
    if is_url(s):
        return "web"
    return "text"


def detect_kind_from_message(msg) -> str:
    """msg is a telegram.Message."""
    if msg.voice:
        return "voice"
    if msg.photo:
        return "image"
    if msg.document:
        name = (msg.document.file_name or "").lower()
        if name.endswith(".pdf"):
            return "pdf"
        if name.endswith(".docx"):
            return "docx"
        if name.endswith(".xlsx") or name.endswith(".xls"):
            return "xlsx"
    if msg.text:
        return detect_kind_from_text(msg.text)
    if msg.caption and (msg.text is None):
        return detect_kind_from_text(msg.caption)
    return "text"
```

- [ ] **Step 3: Run, PASS**

- [ ] **Step 4: Commit**

```bash
git add src/core/kind.py tests/test_kind.py
git commit -m "feat(core): kind detection from text and Telegram messages"
```

---

## Phase 6 — Ingest pipeline

### Task 27: Ingest service (orchestrates extractor + embed + store)

**Files:**
- Create: `src/core/ingest.py`
- Create: `tests/test_ingest.py`

- [ ] **Step 1: Write the failing test (mocked extractor + Jina)**

```python
# tests/test_ingest.py
import pytest
from unittest.mock import AsyncMock
from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner, update_owner_field
from src.core.ingest import ingest_text
from src.core.notes import get_note


@pytest.mark.asyncio
async def test_ingest_text_stores_note_and_embedding(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    update_owner_field(conn, 1, "jina_api_key", "k")

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.1] * 1024)

    note_id = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-100, tg_message_id=42,
        text="привет мир", caption=None, created_at=1000,
    )
    assert note_id is not None
    n = get_note(conn, note_id)
    assert n.content == "привет мир"
    assert n.kind == "text"
    fake_jina.embed.assert_awaited_once()
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Write `src/core/ingest.py`**

```python
import sqlite3
from typing import Optional

from src.core.kind import detect_kind_from_text
from src.core.models import Note
from src.core.notes import insert_note
from src.core.vec import upsert_embedding


async def ingest_text(conn: sqlite3.Connection, *, jina, owner_id: int,
                      tg_chat_id: int, tg_message_id: int,
                      text: str, caption: Optional[str], created_at: int) -> Optional[int]:
    if not text.strip():
        return None
    kind = detect_kind_from_text(text)
    title = _make_title(text)

    note = Note(
        owner_id=owner_id, tg_message_id=tg_message_id, tg_chat_id=tg_chat_id,
        kind=kind, title=title, content=text.strip(),
        source_url=text.strip() if kind in ("web", "youtube") else None,
        raw_caption=caption, created_at=created_at,
    )
    note_id = insert_note(conn, note)
    if note_id is None:
        return None  # duplicate
    embedding = await jina.embed(text.strip(), role="passage")
    upsert_embedding(conn, note_id, embedding)
    return note_id


def _make_title(text: str) -> str:
    first_line = text.strip().splitlines()[0]
    return first_line[:80]
```

- [ ] **Step 4: Run tests, expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/core/ingest.py tests/test_ingest.py
git commit -m "feat(core): text ingestion (kind detection, embed, store)"
```

---

### Task 28: Extend ingest to handle URLs (web/youtube)

**Files:**
- Modify: `src/core/ingest.py`
- Modify: `tests/test_ingest.py`

- [ ] **Step 1: Add tests for URL ingestion**

```python
# tests/test_ingest.py (append)
@pytest.mark.asyncio
async def test_ingest_url_uses_web_extractor(tmp_path, monkeypatch):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    monkeypatch.setattr(
        "src.core.ingest.extract_web",
        lambda url: ("Title", "Article body text"),
    )

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)

    note_id = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=1,
        text="https://example.com/x", caption=None, created_at=1,
    )
    n = get_note(conn, note_id)
    assert n.kind == "web"
    assert n.title == "Title"
    assert "Article body text" in n.content
    assert n.source_url == "https://example.com/x"
```

- [ ] **Step 2: Update `src/core/ingest.py` to call extractors based on kind**

Replace the body of `ingest_text` with:

```python
async def ingest_text(conn: sqlite3.Connection, *, jina, owner_id: int,
                      tg_chat_id: int, tg_message_id: int,
                      text: str, caption: Optional[str], created_at: int) -> Optional[int]:
    if not text.strip():
        return None
    raw = text.strip()
    kind = detect_kind_from_text(raw)

    title: Optional[str] = None
    body = raw
    source_url: Optional[str] = None

    if kind == "web":
        from src.adapters.extractors.web import extract_web
        title, body = extract_web(raw)
        source_url = raw
        body = body or raw
    elif kind == "youtube":
        from src.adapters.extractors.youtube import extract_youtube
        title, body = extract_youtube(raw)
        source_url = raw
        body = body or raw
    else:
        title = _make_title(raw)

    note = Note(
        owner_id=owner_id, tg_message_id=tg_message_id, tg_chat_id=tg_chat_id,
        kind=kind, title=title, content=body.strip(),
        source_url=source_url, raw_caption=caption, created_at=created_at,
    )
    note_id = insert_note(conn, note)
    if note_id is None:
        return None
    embedding = await jina.embed(body.strip()[:8000], role="passage")
    upsert_embedding(conn, note_id, embedding)
    return note_id
```

(import at top: `from src.adapters.extractors.web import extract_web`)

- [ ] **Step 3: Run all ingest tests, PASS**

- [ ] **Step 4: Commit**

```bash
git add src/core/ingest.py tests/test_ingest.py
git commit -m "feat(core): web and youtube extraction during ingest"
```

---

### Task 29: Ingest voice messages

**Files:**
- Modify: `src/core/ingest.py` (add `ingest_voice`)
- Modify: `tests/test_ingest.py`

- [ ] **Step 1: Test**

```python
@pytest.mark.asyncio
async def test_ingest_voice_transcribes_and_stores(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    fake_dg = AsyncMock()
    fake_dg.transcribe = AsyncMock(return_value="голосовая заметка")
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)

    from src.core.ingest import ingest_voice
    note_id = await ingest_voice(
        conn, deepgram=fake_dg, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=10,
        audio_bytes=b"FAKE", mime="audio/ogg", caption=None, created_at=1,
    )
    n = get_note(conn, note_id)
    assert n.kind == "voice"
    assert n.content == "голосовая заметка"
```

- [ ] **Step 2: Add `ingest_voice` to `src/core/ingest.py`**

```python
async def ingest_voice(conn: sqlite3.Connection, *, deepgram, jina,
                        owner_id: int, tg_chat_id: int, tg_message_id: int,
                        audio_bytes: bytes, mime: str,
                        caption: Optional[str], created_at: int) -> Optional[int]:
    transcript = await deepgram.transcribe(audio_bytes, mime=mime)
    if not transcript.strip():
        return None

    note = Note(
        owner_id=owner_id, tg_message_id=tg_message_id, tg_chat_id=tg_chat_id,
        kind="voice", title=_make_title(transcript), content=transcript.strip(),
        raw_caption=caption, created_at=created_at,
    )
    note_id = insert_note(conn, note)
    if note_id is None:
        return None
    embedding = await jina.embed(transcript[:8000], role="passage")
    upsert_embedding(conn, note_id, embedding)
    return note_id
```

- [ ] **Step 3: Test PASS**

- [ ] **Step 4: Commit**

```bash
git add src/core/ingest.py tests/test_ingest.py
git commit -m "feat(core): voice ingestion via Deepgram"
```

---

### Task 30: Ingest documents (PDF/DOCX/XLSX) and images (OCR)

**Files:**
- Modify: `src/core/ingest.py`
- Modify: `tests/test_ingest.py`

- [ ] **Step 1: Test for documents**

```python
@pytest.mark.asyncio
async def test_ingest_document_pdf(tmp_path, monkeypatch):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    monkeypatch.setattr(
        "src.core.ingest.extract_pdf",
        lambda path: "PDF content text",
    )
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)

    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-")

    from src.core.ingest import ingest_document
    note_id = await ingest_document(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=20,
        local_path=pdf_path, original_name="doc.pdf",
        kind="pdf", file_size=5,
        caption="мой пдф", created_at=1, is_oversized=False,
    )
    from src.core.notes import get_note
    from src.core.attachments import list_attachments
    n = get_note(conn, note_id)
    assert n.kind == "pdf"
    assert "PDF content text" in n.content
    atts = list_attachments(conn, note_id)
    assert atts[0].original_name == "doc.pdf"


@pytest.mark.asyncio
async def test_ingest_oversized_records_metadata_only(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)

    from src.core.ingest import ingest_document
    note_id = await ingest_document(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=21,
        local_path=None, original_name="big.zip",
        kind="oversized", file_size=99_000_000,
        caption="архив", created_at=1, is_oversized=True,
    )
    from src.core.notes import get_note
    n = get_note(conn, note_id)
    assert n.kind == "oversized"
    assert "big.zip" in n.content
```

- [ ] **Step 2: Add to `src/core/ingest.py`**

```python
from pathlib import Path

from src.adapters.extractors.pdf import extract_pdf
from src.adapters.extractors.docx import extract_docx
from src.adapters.extractors.xlsx import extract_xlsx
from src.adapters.extractors.ocr import extract_ocr
from src.core.models import Attachment
from src.core.attachments import insert_attachment


async def ingest_document(conn: sqlite3.Connection, *, jina, owner_id: int,
                          tg_chat_id: int, tg_message_id: int,
                          local_path: Optional[Path], original_name: str,
                          kind: str, file_size: int,
                          caption: Optional[str], created_at: int,
                          is_oversized: bool) -> Optional[int]:
    if is_oversized:
        body = f"[oversized] {original_name} ({file_size} bytes)\n{caption or ''}"
        title = original_name
    elif kind == "pdf":
        body = extract_pdf(local_path)
        title = original_name
    elif kind == "docx":
        body = extract_docx(local_path)
        title = original_name
    elif kind == "xlsx":
        body = extract_xlsx(local_path)
        title = original_name
    elif kind == "image":
        body = extract_ocr(local_path) or original_name
        title = caption or original_name
    else:
        body = caption or original_name
        title = original_name

    note = Note(
        owner_id=owner_id, tg_message_id=tg_message_id, tg_chat_id=tg_chat_id,
        kind=kind, title=title, content=body.strip() or original_name,
        raw_caption=caption, created_at=created_at,
    )
    note_id = insert_note(conn, note)
    if note_id is None:
        return None

    insert_attachment(conn, Attachment(
        note_id=note_id,
        file_path=str(local_path) if local_path else "",
        file_size=file_size,
        original_name=original_name,
        is_oversized=is_oversized,
    ))

    if not is_oversized and body.strip():
        embedding = await jina.embed(body.strip()[:8000], role="passage")
        upsert_embedding(conn, note_id, embedding)
    return note_id
```

- [ ] **Step 3: Run tests, PASS**

- [ ] **Step 4: Commit**

```bash
git add src/core/ingest.py tests/test_ingest.py
git commit -m "feat(core): document and image ingestion (PDF/DOCX/XLSX/OCR)"
```

---

### Task 31: Channel handler (Telegram → ingest pipeline)

**Files:**
- Create: `src/bot/handlers/channel.py`

- [ ] **Step 1: Write `src/bot/handlers/channel.py`**

```python
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import Application, ChannelPostHandler, ContextTypes

from src.adapters.deepgram import DeepgramClient
from src.adapters.jina import JinaClient
from src.adapters.tg_files import is_oversized
from src.bot.handlers.reactions import (
    set_reaction, PROCESSING, SUCCESS, FAILURE, OVERSIZED,
)
from src.core.ingest import ingest_text, ingest_voice, ingest_document
from src.core.kind import detect_kind_from_message
from src.core.owners import get_owner

logger = logging.getLogger(__name__)


async def channel_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    owner = get_owner(conn, settings.owner_telegram_id)

    if not owner or owner.setup_step != "done":
        return  # bot not configured yet
    if owner.inbox_chat_id is None or update.channel_post.chat.id != owner.inbox_chat_id:
        return

    msg = update.channel_post
    chat_id = msg.chat.id
    msg_id = msg.message_id

    await set_reaction(ctx.bot, chat_id, msg_id, PROCESSING)
    try:
        await _route_and_ingest(ctx, conn, owner, msg)
        await set_reaction(ctx.bot, chat_id, msg_id, SUCCESS)
    except _OversizedFile:
        await set_reaction(ctx.bot, chat_id, msg_id, OVERSIZED)
    except Exception:
        logger.exception("ingest failed")
        await set_reaction(ctx.bot, chat_id, msg_id, FAILURE)


class _OversizedFile(Exception):
    pass


async def _route_and_ingest(ctx, conn, owner, msg) -> None:
    kind = detect_kind_from_message(msg)
    jina = JinaClient(api_key=owner.jina_api_key)
    deepgram = DeepgramClient(api_key=owner.deepgram_api_key)

    if kind in ("text", "web", "youtube"):
        text = msg.text or msg.caption or ""
        await ingest_text(
            conn, jina=jina, owner_id=owner.telegram_id,
            tg_chat_id=msg.chat.id, tg_message_id=msg.message_id,
            text=text, caption=msg.caption, created_at=int(msg.date.timestamp()),
        )
        return

    if kind == "voice":
        voice = msg.voice
        if is_oversized(voice.file_size or 0):
            raise _OversizedFile
        f = await ctx.bot.get_file(voice.file_id)
        audio = await f.download_as_bytearray()
        await ingest_voice(
            conn, deepgram=deepgram, jina=jina, owner_id=owner.telegram_id,
            tg_chat_id=msg.chat.id, tg_message_id=msg.message_id,
            audio_bytes=bytes(audio), mime=voice.mime_type or "audio/ogg",
            caption=msg.caption, created_at=int(msg.date.timestamp()),
        )
        return

    if kind in ("pdf", "docx", "xlsx"):
        doc = msg.document
        size = doc.file_size or 0
        if is_oversized(size):
            await ingest_document(
                conn, jina=jina, owner_id=owner.telegram_id,
                tg_chat_id=msg.chat.id, tg_message_id=msg.message_id,
                local_path=None, original_name=doc.file_name,
                kind="oversized", file_size=size,
                caption=msg.caption, created_at=int(msg.date.timestamp()),
                is_oversized=True,
            )
            raise _OversizedFile

        f = await ctx.bot.get_file(doc.file_id)
        local_dir = Path("/app/data/attachments") / str(msg.message_id)
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / doc.file_name
        await f.download_to_drive(custom_path=str(local_path))

        await ingest_document(
            conn, jina=jina, owner_id=owner.telegram_id,
            tg_chat_id=msg.chat.id, tg_message_id=msg.message_id,
            local_path=local_path, original_name=doc.file_name,
            kind=kind, file_size=size,
            caption=msg.caption, created_at=int(msg.date.timestamp()),
            is_oversized=False,
        )
        return

    if kind == "image":
        photo = msg.photo[-1]  # largest
        size = photo.file_size or 0
        if is_oversized(size):
            raise _OversizedFile
        f = await ctx.bot.get_file(photo.file_id)
        local_dir = Path("/app/data/attachments") / str(msg.message_id)
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / f"photo_{photo.file_unique_id}.jpg"
        await f.download_to_drive(custom_path=str(local_path))

        await ingest_document(
            conn, jina=jina, owner_id=owner.telegram_id,
            tg_chat_id=msg.chat.id, tg_message_id=msg.message_id,
            local_path=local_path, original_name=local_path.name,
            kind="image", file_size=size,
            caption=msg.caption, created_at=int(msg.date.timestamp()),
            is_oversized=False,
        )
        return


def register_channel_handlers(app: Application) -> None:
    app.add_handler(ChannelPostHandler(channel_handler))
```

- [ ] **Step 2: Test that imports compose**

Run: `pytest tests/test_main_imports.py`

- [ ] **Step 3: Commit**

```bash
git add src/bot/handlers/channel.py
git commit -m "feat(bot): channel handler routes posts to ingest pipeline"
```

---

## Phase 7 — Search pipeline

### Task 32: Intent parser (LLM-based)

**Files:**
- Create: `src/core/intent.py`
- Create: `tests/test_intent.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_intent.py
import pytest
from unittest.mock import AsyncMock
from src.core.intent import parse_intent, IntentResult


@pytest.mark.asyncio
async def test_parse_intent_passthrough_when_llm_fails():
    fake = AsyncMock()
    fake.complete = AsyncMock(side_effect=Exception("down"))
    out = await parse_intent(fake, primary="x", fallback="y", query="что я сохранял про пасту")
    assert out.clean_query == "что я сохранял про пасту"
    assert out.kind is None


@pytest.mark.asyncio
async def test_parse_intent_extracts_kind_filter():
    fake = AsyncMock()
    fake.complete = AsyncMock(return_value='{"clean_query": "паста рецепт", "kind": "voice"}')
    out = await parse_intent(fake, primary="x", fallback="y",
                              query="голосовуха про пасту")
    assert out.clean_query == "паста рецепт"
    assert out.kind == "voice"
```

- [ ] **Step 2: Write `src/core/intent.py`**

```python
import json
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

PROMPT = """Ты — парсер поисковых запросов для личной базы знаний.
Извлеки из запроса пользователя:
- clean_query: основные ключевые слова без шума ("найди", "покажи", "что я сохранял про")
- kind: если фильтр по типу контента очевиден, верни одно из: text|voice|youtube|web|pdf|docx|xlsx|image. Иначе null.

Верни ТОЛЬКО валидный JSON, ничего больше. Пример: {"clean_query": "паста рецепт", "kind": null}.

Запрос: """


@dataclass(frozen=True)
class IntentResult:
    clean_query: str
    kind: Optional[str]


async def parse_intent(openrouter, primary: str, fallback: Optional[str],
                       query: str) -> IntentResult:
    try:
        raw = await openrouter.complete(
            primary=primary, fallback=fallback,
            messages=[{"role": "user", "content": PROMPT + query}],
            max_tokens=200,
        )
        data = json.loads(raw)
        clean = data.get("clean_query", query) or query
        kind = data.get("kind")
        if kind not in {"text", "voice", "youtube", "web", "pdf", "docx", "xlsx", "image"}:
            kind = None
        return IntentResult(clean_query=clean, kind=kind)
    except Exception as e:
        logger.warning("intent parse failed (%s); falling back to passthrough", e)
        return IntentResult(clean_query=query, kind=None)
```

- [ ] **Step 3: Run, PASS**

- [ ] **Step 4: Commit**

```bash
git add src/core/intent.py tests/test_intent.py
git commit -m "feat(core): LLM-based intent parser with passthrough fallback"
```

---

### Task 33: Hybrid search (BM25 + vec + RRF)

**Files:**
- Create: `src/core/search.py`
- Create: `tests/test_search.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_search.py
import pytest
from unittest.mock import AsyncMock
from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner
from src.core.notes import insert_note
from src.core.vec import upsert_embedding
from src.core.models import Note
from src.core.search import hybrid_search


def _seed(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    docs = [
        ("cats love tuna fish", [1.0, 0.0] + [0.0] * 1022),
        ("dogs eat bones daily", [0.0, 1.0] + [0.0] * 1022),
        ("tuna sushi recipe", [0.9, 0.1] + [0.0] * 1022),
    ]
    for i, (content, emb) in enumerate(docs):
        nid = insert_note(conn, Note(
            owner_id=1, tg_message_id=i, tg_chat_id=-1,
            kind="text", content=content, created_at=1,
        ))
        upsert_embedding(conn, nid, emb)
    return conn


@pytest.mark.asyncio
async def test_hybrid_search_finds_relevant(tmp_path):
    conn = _seed(tmp_path)
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[1.0, 0.0] + [0.0] * 1022)

    results = await hybrid_search(
        conn, jina=fake_jina, owner_id=1,
        clean_query="tuna", kind=None, limit=5,
    )
    contents = [r.content for r in results]
    assert any("tuna" in c.lower() for c in contents)
```

- [ ] **Step 2: Write `src/core/search.py`**

```python
import sqlite3
from typing import Optional

from src.core.notes import get_note
from src.core.vec import search_similar
from src.core.models import Note


async def hybrid_search(conn: sqlite3.Connection, *, jina, owner_id: int,
                        clean_query: str, kind: Optional[str],
                        limit: int = 15) -> list[Note]:
    bm25_ids = _bm25(conn, owner_id, clean_query, kind, k=30)
    embedding = await jina.embed(clean_query, role="query")
    vec_pairs = search_similar(conn, embedding, limit=30)
    vec_ids = [pair[0] for pair in vec_pairs]
    fused = _rrf(bm25_ids, vec_ids)[:limit]
    notes = [get_note(conn, nid) for nid in fused]
    notes = [n for n in notes if n and n.owner_id == owner_id]
    if kind:
        notes = [n for n in notes if n.kind == kind]
    return notes[:limit]


def _bm25(conn: sqlite3.Connection, owner_id: int,
          query: str, kind: Optional[str], k: int) -> list[int]:
    sql = """SELECT n.id
             FROM notes_fts
             JOIN notes n ON n.id = notes_fts.rowid
             WHERE notes_fts MATCH ? AND n.owner_id = ?"""
    params: list = [_sanitize_fts(query), owner_id]
    if kind:
        sql += " AND n.kind = ?"
        params.append(kind)
    sql += " ORDER BY rank LIMIT ?"
    params.append(k)
    return [row[0] for row in conn.execute(sql, params).fetchall()]


def _sanitize_fts(query: str) -> str:
    # Quote tokens to avoid FTS5 syntax errors on punctuation.
    tokens = [t for t in query.split() if t]
    return " ".join(f'"{t}"' for t in tokens) or '""'


def _rrf(*ranked_lists: list[int], k: int = 60) -> list[int]:
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return [doc_id for doc_id, _ in sorted(scores.items(), key=lambda x: -x[1])]
```

- [ ] **Step 3: Run, PASS**

- [ ] **Step 4: Commit**

```bash
git add src/core/search.py tests/test_search.py
git commit -m "feat(core): hybrid search (BM25 + vec + RRF)"
```

---

### Task 34: LLM reranker

**Files:**
- Modify: `src/core/search.py` to add `rerank`
- Modify: `tests/test_search.py`

- [ ] **Step 1: Test**

```python
# append to tests/test_search.py
@pytest.mark.asyncio
async def test_rerank_orders_by_llm_response(tmp_path):
    conn = _seed(tmp_path)
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[1.0, 0.0] + [0.0] * 1022)
    fake_or = AsyncMock()
    # LLM returns a JSON list of ids in best-first order
    fake_or.complete = AsyncMock(return_value="[3, 1]")

    from src.core.search import rerank, hybrid_search
    candidates = await hybrid_search(
        conn, jina=fake_jina, owner_id=1,
        clean_query="tuna", kind=None, limit=5,
    )
    reranked = await rerank(
        fake_or, primary="x", fallback="y",
        query="tuna sushi", candidates=candidates, top_k=2,
    )
    assert [n.id for n in reranked] == [3, 1]
```

- [ ] **Step 2: Add `rerank` to `src/core/search.py`**

```python
import json
import logging

logger = logging.getLogger(__name__)

RERANK_PROMPT = """Ты — реранкер результатов поиска для личной базы знаний.
Запрос: {query}

Кандидаты (id и фрагмент):
{candidates}

Верни JSON-массив id в порядке релевантности (сначала самый релевантный),
не больше {top_k} элементов. Пример: [12, 5, 8].
Если ни один не релевантен — верни пустой массив [].
ТОЛЬКО JSON, ничего больше.
"""


async def rerank(openrouter, primary: str, fallback: Optional[str],
                 query: str, candidates: list[Note], top_k: int = 5) -> list[Note]:
    if not candidates:
        return []

    blocks = "\n\n".join(
        f"id={n.id}: {(n.title or '')[:80]}\n{n.content[:300]}"
        for n in candidates
    )
    try:
        raw = await openrouter.complete(
            primary=primary, fallback=fallback,
            messages=[{"role": "user", "content": RERANK_PROMPT.format(
                query=query, candidates=blocks, top_k=top_k,
            )}],
            max_tokens=200,
        )
        ids = json.loads(raw)
    except Exception as e:
        logger.warning("rerank failed (%s); using hybrid order", e)
        return candidates[:top_k]

    by_id = {n.id: n for n in candidates}
    ordered = [by_id[i] for i in ids if i in by_id]
    return ordered[:top_k]
```

- [ ] **Step 3: Run, PASS**

- [ ] **Step 4: Commit**

```bash
git add src/core/search.py tests/test_search.py
git commit -m "feat(core): LLM reranker with hybrid-order fallback"
```

---

### Task 35: Telegram link builder

**Files:**
- Create: `src/core/links.py`
- Create: `tests/test_links.py`

- [ ] **Step 1: Test**

```python
# tests/test_links.py
from src.core.links import message_link

def test_message_link_for_private_channel():
    assert message_link(chat_id=-1001234567890, message_id=42) == \
        "https://t.me/c/1234567890/42"

def test_message_link_for_username():
    # We don't support public usernames yet (private channel only)
    assert message_link(chat_id=-1009999999999, message_id=1) == \
        "https://t.me/c/9999999999/1"
```

- [ ] **Step 2: Write `src/core/links.py`**

```python
def message_link(chat_id: int, message_id: int) -> str:
    """Build a t.me link for a private channel message.

    Telegram's private channel chat IDs have format -100<id>; the public link
    drops the -100 prefix.
    """
    chat_str = str(chat_id)
    if chat_str.startswith("-100"):
        chat_str = chat_str[4:]
    return f"https://t.me/c/{chat_str}/{message_id}"
```

- [ ] **Step 3: Run, PASS**

- [ ] **Step 4: Commit**

```bash
git add src/core/links.py tests/test_links.py
git commit -m "feat(core): Telegram message link builder for private channels"
```

---

### Task 36: Search handler (DM messages)

**Files:**
- Create: `src/bot/handlers/search.py`

- [ ] **Step 1: Write `src/bot/handlers/search.py`**

```python
import logging
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from src.adapters.deepgram import DeepgramClient
from src.adapters.jina import JinaClient
from src.adapters.openrouter import OpenRouterClient
from src.bot.auth import is_owner
from src.core.intent import parse_intent
from src.core.links import message_link
from src.core.owners import get_owner
from src.core.search import hybrid_search, rerank

logger = logging.getLogger(__name__)


async def search_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]

    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return

    owner = get_owner(conn, settings.owner_telegram_id)
    if not owner or owner.setup_step != "done":
        return  # setup wizard takes priority

    msg = update.message
    if msg.text and msg.text.startswith("/"):
        return  # commands handled elsewhere

    query_text = await _query_text(msg, owner, ctx)
    if not query_text.strip():
        return

    openrouter = OpenRouterClient(api_key=owner.openrouter_key)
    jina = JinaClient(api_key=owner.jina_api_key)

    intent = await parse_intent(
        openrouter, primary=owner.primary_model,
        fallback=owner.fallback_model, query=query_text,
    )

    candidates = await hybrid_search(
        conn, jina=jina, owner_id=owner.telegram_id,
        clean_query=intent.clean_query, kind=intent.kind, limit=15,
    )
    if not candidates:
        await msg.reply_text("Не нашёл ничего. Попробуй уточнить запрос.")
        return

    reranked = await rerank(
        openrouter, primary=owner.primary_model, fallback=owner.fallback_model,
        query=intent.clean_query, candidates=candidates, top_k=5,
    )
    if not reranked:
        await msg.reply_text("Не нашёл ничего релевантного.")
        return

    chunks = [_format_hit(n) for n in reranked]
    await msg.reply_text("\n\n─────\n\n".join(chunks),
                         disable_web_page_preview=True)


async def _query_text(msg, owner, ctx) -> str:
    if msg.voice:
        deepgram = DeepgramClient(api_key=owner.deepgram_api_key)
        f = await ctx.bot.get_file(msg.voice.file_id)
        audio = await f.download_as_bytearray()
        return await deepgram.transcribe(bytes(audio), mime=msg.voice.mime_type or "audio/ogg")
    return msg.text or ""


def _format_hit(note) -> str:
    link = message_link(note.tg_chat_id, note.tg_message_id)
    title = (note.title or "")[:80]
    snippet = note.content[:200]
    return f"📌 [{note.kind}] {title}\n{link}\n{snippet}"


def register_search_handlers(app: Application) -> None:
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.FORWARDED & ~filters.COMMAND,
        search_handler,
    ))
```

- [ ] **Step 2: Test imports**

Run: `pytest tests/test_main_imports.py`

- [ ] **Step 3: Commit**

```bash
git add src/bot/handlers/search.py
git commit -m "feat(bot): DM search handler (text and voice)"
```

---

## Phase 8 — Commands

### Task 37: `/help` and `/status`

**Files:**
- Create: `src/bot/handlers/commands.py`

- [ ] **Step 1: Write `src/bot/handlers/commands.py`**

```python
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from src.bot.auth import is_owner
from src.core.owners import get_owner

HELP_TEXT = (
    "*Soroka — команды*\n\n"
    "Канал «Избранное 2» — кидай туда что угодно.\n"
    "DM (этот чат) — пиши/говори запрос для поиска.\n\n"
    "/start — мастер настройки\n"
    "/status — текущие настройки\n"
    "/setjina — заменить ключ Jina\n"
    "/setdeepgram — заменить ключ Deepgram\n"
    "/setkey — заменить ключ OpenRouter\n"
    "/models — выбрать модели primary/fallback\n"
    "/setgithub — заменить GitHub-токен и репо\n"
    "/setvps — задать IP/юзера VPS (для /mcp)\n"
    "/setinbox — сменить канал-инбокс\n"
    "/export — выгрузить базу архивом\n"
    "/mcp — конфиг для Claude Desktop\n"
    "/cancel — прервать текущий мастер"
)


async def help_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def status_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return

    owner = get_owner(conn, settings.owner_telegram_id)
    if not owner:
        await update.message.reply_text("Бот ещё не настроен. /start")
        return

    notes_count = conn.execute(
        "SELECT count(*) FROM notes WHERE owner_id = ?",
        (owner.telegram_id,),
    ).fetchone()[0]

    def _mask(v: str | None) -> str:
        if not v:
            return "❌"
        return f"…{v[-4:]} ✓"

    text = (
        f"*Soroka /status*\n\n"
        f"🔑 Jina:       {_mask(owner.jina_api_key)}\n"
        f"🔑 Deepgram:   {_mask(owner.deepgram_api_key)}\n"
        f"🔑 OpenRouter: {_mask(owner.openrouter_key)}\n"
        f"🟢 primary:    `{owner.primary_model or '—'}`\n"
        f"🟡 fallback:   `{owner.fallback_model or '—'}`\n"
        f"💾 GitHub:     `{owner.github_mirror_repo or '—'}`\n"
        f"📺 Inbox:      `{owner.inbox_chat_id or '—'}`\n"
        f"📊 Notes:       {notes_count}\n"
        f"⚙ Setup step:  `{owner.setup_step}`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cancel_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return
    # Clear pending diag state if any (set by /set* commands)
    ctx.user_data.pop("pending_set", None)
    await update.message.reply_text("Отменено.")


def register_command_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
```

- [ ] **Step 2: Test imports**

- [ ] **Step 3: Commit**

```bash
git add src/bot/handlers/commands.py
git commit -m "feat(bot): /help, /status, /cancel"
```

---

### Task 38: `/set*` commands (jina, deepgram, key, github, vps, inbox)

**Files:**
- Modify: `src/bot/handlers/commands.py`
- Modify: `src/bot/handlers/setup.py` (route plain DM messages to active /set* prompt before search)

- [ ] **Step 1: Add `/set*` commands using `ctx.user_data["pending_set"]` state**

In `src/bot/handlers/commands.py`, add:

```python
from telegram.ext import MessageHandler, filters

PENDING_PROMPTS = {
    "jina":      ("jina_api_key", "Пришли новый ключ Jina."),
    "deepgram":  ("deepgram_api_key", "Пришли новый ключ Deepgram."),
    "key":       ("openrouter_key", "Пришли новый ключ OpenRouter."),
    "github":    ("github_pair", "Пришли одной строкой: `<token> <user>/<repo>`."),
    "vps":       ("vps_pair", "Пришли одной строкой: `<user>@<ip>` (например `andrey@65.21.45.122`)."),
    "inbox":     ("inbox", "Форвардни сюда сообщение из нового канала."),
}


def _make_set_command(kind: str):
    async def handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        settings = ctx.application.bot_data["settings"]
        if not is_owner(update.effective_user.id, settings.owner_telegram_id):
            return
        ctx.user_data["pending_set"] = kind
        _, prompt = PENDING_PROMPTS[kind]
        await update.message.reply_text(prompt, parse_mode="Markdown")
    return handler


async def pending_set_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return
    pending = ctx.user_data.get("pending_set")
    if not pending:
        return  # let other handlers (search) act

    text = (update.message.text or "").strip()
    from src.adapters.jina import JinaClient
    from src.adapters.deepgram import DeepgramClient
    from src.adapters.openrouter import OpenRouterClient
    from src.adapters.github_mirror import GitHubMirror, GitHubMirrorError
    from src.core.owners import update_owner_field

    owner_id = settings.owner_telegram_id

    if pending == "jina":
        if not await JinaClient(api_key=text).validate_key():
            await update.message.reply_text("Не подошёл. Попробуй ещё раз или /cancel.")
            return
        update_owner_field(conn, owner_id, "jina_api_key", text)

    elif pending == "deepgram":
        if not await DeepgramClient(api_key=text).validate_key():
            await update.message.reply_text("Не подошёл. /cancel или попробуй ещё раз.")
            return
        update_owner_field(conn, owner_id, "deepgram_api_key", text)

    elif pending == "key":
        if not await OpenRouterClient(api_key=text).validate_key():
            await update.message.reply_text("Не подошёл. /cancel или попробуй ещё раз.")
            return
        update_owner_field(conn, owner_id, "openrouter_key", text)

    elif pending == "github":
        parts = text.split()
        if len(parts) != 2 or "/" not in parts[1]:
            await update.message.reply_text("Формат: `<token> <user>/<repo>`. /cancel или попробуй ещё раз.")
            return
        try:
            await GitHubMirror(token=parts[0], repo=parts[1]).validate()
        except GitHubMirrorError as e:
            await update.message.reply_text(f"GitHub: {e}. /cancel или попробуй ещё раз.")
            return
        update_owner_field(conn, owner_id, "github_token", parts[0])
        update_owner_field(conn, owner_id, "github_mirror_repo", parts[1])

    elif pending == "vps":
        if "@" not in text:
            await update.message.reply_text("Формат: `<user>@<ip>`. /cancel или попробуй ещё раз.")
            return
        user, host = text.split("@", 1)
        update_owner_field(conn, owner_id, "vps_user", user)
        update_owner_field(conn, owner_id, "vps_host", host)

    elif pending == "inbox":
        msg = update.message
        if not msg.forward_origin or msg.forward_origin.type != "channel":
            await update.message.reply_text("Это не форвард из канала. /cancel или попробуй ещё раз.")
            return
        update_owner_field(conn, owner_id, "inbox_chat_id", msg.forward_origin.chat.id)

    ctx.user_data.pop("pending_set", None)
    await update.message.reply_text("✓ Готово.")
```

Update `register_command_handlers`:

```python
def register_command_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    for kind in PENDING_PROMPTS:
        app.add_handler(CommandHandler(f"set{kind}", _make_set_command(kind)))
    # The pending-set handler must run BEFORE search handler.
    # python-telegram-bot dispatches by registration order within a group;
    # explicit higher-priority group ensures this.
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.COMMAND,
        pending_set_handler,
    ), group=-1)
```

- [ ] **Step 2: Test imports**

- [ ] **Step 3: Commit**

```bash
git add src/bot/handlers/commands.py
git commit -m "feat(bot): /set* commands for changing each key after setup"
```

---

### Task 39: `/mcp` command

**Files:**
- Modify: `src/bot/handlers/commands.py`

- [ ] **Step 1: Add `/mcp` handler**

```python
async def mcp_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return

    owner = get_owner(conn, settings.owner_telegram_id)
    if not owner or not owner.vps_host or not owner.vps_user:
        await update.message.reply_text(
            "Сначала задай VPS-доступ через /setvps "
            "(нужны для генерации SSH-команды в конфиге).")
        return

    config = (
        '{\n'
        '  "mcpServers": {\n'
        '    "soroka": {\n'
        '      "command": "ssh",\n'
        f'      "args": ["{owner.vps_user}@{owner.vps_host}", "soroka-mcp"]\n'
        '    }\n'
        '  }\n'
        '}'
    )
    text = (
        "Скопируй этот блок в файл `claude_desktop_config.json`:\n"
        "• Mac: `~/Library/Application Support/Claude/claude_desktop_config.json`\n"
        "• Windows: `%APPDATA%\\Claude\\claude_desktop_config.json`\n\n"
        f"```json\n{config}\n```\n\n"
        "Перезапусти Claude Desktop. В беседе появится инструмент `soroka`."
    )
    await update.message.reply_text(text, parse_mode="Markdown")
```

Add to `register_command_handlers`:

```python
    app.add_handler(CommandHandler("mcp", mcp_command))
```

- [ ] **Step 2: Test imports**

- [ ] **Step 3: Commit**

```bash
git add src/bot/handlers/commands.py
git commit -m "feat(bot): /mcp prints SSH-stdio config for Claude Desktop"
```

---

## Phase 9 — Export & GitHub mirror

### Task 40: Export builder

**Files:**
- Create: `src/core/export.py`
- Create: `tests/test_export.py`

- [ ] **Step 1: Test**

```python
# tests/test_export.py
import json
from pathlib import Path
import zipfile
from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner
from src.core.notes import insert_note
from src.core.models import Note
from src.core.export import build_export


def test_build_export_zip(tmp_path):
    db_path = tmp_path / "x.db"
    conn = open_db(str(db_path))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    insert_note(conn, Note(
        owner_id=1, tg_message_id=1, tg_chat_id=-1,
        kind="text", content="hello", created_at=1,
    ))
    conn.close()

    out = tmp_path / "export.zip"
    build_export(
        db_path=db_path,
        attachments_dir=tmp_path / "atts",
        output_path=out,
    )
    assert out.exists()
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "soroka.db" in names
        assert "notes.json" in names
        with z.open("notes.json") as f:
            data = json.load(f)
        assert data[0]["content"] == "hello"
```

- [ ] **Step 2: Write `src/core/export.py`**

```python
import json
import sqlite3
import zipfile
from pathlib import Path
from typing import Optional


def build_export(*, db_path: Path, attachments_dir: Optional[Path],
                 output_path: Path, lite: bool = False) -> Path:
    notes = _read_notes(db_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.write(db_path, arcname="soroka.db")
        z.writestr("notes.json", json.dumps(notes, ensure_ascii=False, indent=2))
        z.writestr("README.md", _readme())

        if not lite and attachments_dir and attachments_dir.exists():
            for path in attachments_dir.rglob("*"):
                if path.is_file():
                    arc = "attachments/" + str(path.relative_to(attachments_dir))
                    z.write(path, arcname=arc)
    return output_path


def _read_notes(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("SELECT id, owner_id, tg_message_id, tg_chat_id, kind, "
                            "title, content, source_url, raw_caption, created_at "
                            "FROM notes ORDER BY id")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def _readme() -> str:
    return (
        "# Soroka export\n\n"
        "- `soroka.db` — full SQLite snapshot (FTS5+vec).\n"
        "- `notes.json` — flat JSON dump of notes.\n"
        "- `attachments/` — files referenced by notes (omitted in lite export).\n"
    )
```

- [ ] **Step 3: Run, PASS**

- [ ] **Step 4: Commit**

```bash
git add src/core/export.py tests/test_export.py
git commit -m "feat(core): export builder (full + lite zip)"
```

---

### Task 41: `/export` command (Telegram path)

**Files:**
- Modify: `src/bot/handlers/commands.py`

- [ ] **Step 1: Add `/export` handler**

```python
import datetime as dt
from pathlib import Path

from src.adapters.github_mirror import GitHubMirror, GitHubMirrorError
from src.core.export import build_export

TG_FILE_LIMIT = 50 * 1024 * 1024
WORK_DIR = Path("/app/data/exports")


async def export_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return
    owner = get_owner(conn, settings.owner_telegram_id)
    if not owner:
        return

    await update.message.reply_text("Собираю архив…")
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    full_path = WORK_DIR / f"soroka-{ts}.zip"
    db_path = Path(settings.db_path)
    attachments_dir = db_path.parent / "attachments"

    build_export(db_path=db_path, attachments_dir=attachments_dir,
                  output_path=full_path, lite=False)

    if full_path.stat().st_size <= TG_FILE_LIMIT:
        with full_path.open("rb") as f:
            await update.message.reply_document(document=f, filename=full_path.name)
        return

    if not (owner.github_token and owner.github_mirror_repo):
        lite_path = WORK_DIR / f"soroka-{ts}-lite.zip"
        build_export(db_path=db_path, attachments_dir=None,
                      output_path=lite_path, lite=True)
        with lite_path.open("rb") as f:
            await update.message.reply_document(document=f, filename=lite_path.name)
        await update.message.reply_text(
            f"Полный архив {full_path.stat().st_size//1024//1024}MB не помещается. "
            "Включи зеркало через /setgithub чтобы я мог отдать ссылку.",
        )
        return

    mirror = GitHubMirror(token=owner.github_token, repo=owner.github_mirror_repo)
    try:
        url = await mirror.upload_release(
            tag=f"backup-{ts}", title=f"Soroka backup {ts}",
            body="Automated backup from /export.", asset=full_path,
        )
    except GitHubMirrorError as e:
        await update.message.reply_text(f"GitHub-зеркало отказало: {e}")
        return

    lite_path = WORK_DIR / f"soroka-{ts}-lite.zip"
    build_export(db_path=db_path, attachments_dir=None,
                  output_path=lite_path, lite=True)
    with lite_path.open("rb") as f:
        await update.message.reply_document(document=f, filename=lite_path.name)
    await update.message.reply_text(f"Полный архив тут: {url}")
```

Add to `register_command_handlers`:

```python
    app.add_handler(CommandHandler("export", export_command))
```

- [ ] **Step 2: Test imports**

- [ ] **Step 3: Commit**

```bash
git add src/bot/handlers/commands.py
git commit -m "feat(bot): /export with GitHub-mirror fallback"
```

---

## Phase 10 — MCP server

### Task 42: MCP stdio server with 4 tools

**Files:**
- Create: `src/mcp/server.py`
- Create: `tests/test_mcp_server.py`

- [ ] **Step 1: Test pure tool functions**

```python
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
```

- [ ] **Step 2: Write `src/mcp/server.py`**

```python
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
```

- [ ] **Step 3: Run tests, PASS**

- [ ] **Step 4: Commit**

```bash
git add src/mcp/server.py tests/test_mcp_server.py
git commit -m "feat(mcp): stdio server with search/get_by_id/list_recent/get_attachment"
```

---

## Phase 11 — Install scripts and docs

### Task 43: `bin/install` script

**Files:**
- Create: `bin/install`
- Create: `bin/update`
- Create: `scripts/soroka-mcp`

- [ ] **Step 1: Write `bin/install`**

```bash
#!/usr/bin/env bash
set -euo pipefail

VPS_IP=""
SSH_USER="root"
SSH_KEY="$HOME/.ssh/id_rsa"
TG_TOKEN=""
OWNER_ID=""
REPO_URL="https://github.com/$(git config --get remote.origin.url 2>/dev/null \
  | sed -E 's#.*github.com[:/](.*?)(\.git)?$#\1#' \
  || echo 'YOUR_USER/soroka').git"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --vps-ip) VPS_IP="$2"; shift 2;;
    --ssh-user) SSH_USER="$2"; shift 2;;
    --ssh-key) SSH_KEY="$2"; shift 2;;
    --tg-token) TG_TOKEN="$2"; shift 2;;
    --owner-id) OWNER_ID="$2"; shift 2;;
    --repo) REPO_URL="$2"; shift 2;;
    *) echo "unknown flag: $1" >&2; exit 1;;
  esac
done

read_if_empty() {
  local var_name="$1" prompt="$2" default="${3:-}"
  if [[ -z "${!var_name}" ]]; then
    if [[ -n "$default" ]]; then
      read -rp "$prompt [$default]: " value
      printf -v "$var_name" "%s" "${value:-$default}"
    else
      read -rp "$prompt: " value
      printf -v "$var_name" "%s" "$value"
    fi
  fi
}

echo "🐦 Soroka — installer"
read_if_empty VPS_IP    "VPS IP"
read_if_empty SSH_USER  "SSH user" "root"
read_if_empty SSH_KEY   "SSH key path" "$HOME/.ssh/id_rsa"
read_if_empty TG_TOKEN  "Telegram bot token (from @BotFather)"
read_if_empty OWNER_ID  "Your Telegram ID (from @userinfobot)"

echo
echo "Verifying SSH..."
ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new "$SSH_USER@$VPS_IP" 'echo ok' >/dev/null
echo "✓ SSH OK"

echo "Deploying..."
ssh -i "$SSH_KEY" "$SSH_USER@$VPS_IP" bash <<EOF
set -euo pipefail

if ! command -v docker >/dev/null; then
  apt-get update
  apt-get install -y docker.io docker-compose-plugin git
fi

mkdir -p /opt
cd /opt
if [[ ! -d soroka ]]; then
  git clone $REPO_URL soroka
fi
cd /opt/soroka
git pull

cat > .env <<ENV
TELEGRAM_BOT_TOKEN=$TG_TOKEN
OWNER_TELEGRAM_ID=$OWNER_ID
ENV
chmod 600 .env

docker compose up -d --build

cp scripts/soroka-mcp /usr/local/bin/
chmod +x /usr/local/bin/soroka-mcp

docker ps | grep soroka-bot >/dev/null && echo "[✓] bot running"
EOF

cat <<MSG

🎉 Готово!
Открой Telegram, найди своего бота и отправь /start.
Дальше всё настроишь в чате с ботом.
MSG
```

- [ ] **Step 2: Make executable**

```bash
chmod +x bin/install
```

- [ ] **Step 3: Write `bin/update`**

```bash
#!/usr/bin/env bash
set -euo pipefail
VPS="$1"
SSH_USER="${2:-root}"
ssh "$SSH_USER@$VPS" 'cd /opt/soroka && git pull && docker compose up -d --build'
```

```bash
chmod +x bin/update
```

- [ ] **Step 4: Write `scripts/soroka-mcp`**

```sh
#!/bin/sh
exec docker exec -i soroka-bot python -m src.mcp.server
```

```bash
chmod +x scripts/soroka-mcp
```

- [ ] **Step 5: Commit**

```bash
git add bin/install bin/update scripts/soroka-mcp
git commit -m "feat: bin/install, bin/update, scripts/soroka-mcp deployment helpers"
```

---

### Task 44: `AGENTS.md`

**Files:**
- Create: `AGENTS.md`

- [ ] **Step 1: Write `AGENTS.md`**

```markdown
# AGENTS.md — Deployment protocol for AI agents

This file is the authoritative protocol for AI agents (Claude Code, Cursor, etc.)
deploying Soroka. Humans should read `README.md`.

## Required values from the user

Ask the user for these (and only these) before doing anything else:

- `VPS_IP`            — public IP of an Ubuntu 22.04+ VPS
- `SSH_USER`          — SSH user (default: `root`)
- `SSH_KEY`           — path to SSH private key (default: `~/.ssh/id_rsa`)
- `TELEGRAM_BOT_TOKEN`— from @BotFather
- `OWNER_TELEGRAM_ID` — from @userinfobot

DO NOT ask the user for any other keys (Jina, Deepgram, OpenRouter, GitHub).
Those are collected later via the bot's `/start` wizard, in Telegram.

## Deployment

Run the installer script in non-interactive mode:

```bash
./bin/install \
  --vps-ip "$VPS_IP" \
  --ssh-user "$SSH_USER" \
  --ssh-key "$SSH_KEY" \
  --tg-token "$TELEGRAM_BOT_TOKEN" \
  --owner-id "$OWNER_TELEGRAM_ID"
```

Verify success:
```bash
ssh "$SSH_USER@$VPS_IP" docker ps | grep soroka-bot
```

## Hand-off

After successful deployment, tell the user:

> "Готово. Открой Telegram, найди своего бота и отправь /start.
>  Бот проведёт через 6 шагов: ключи Jina, Deepgram, OpenRouter,
>  выбор моделей, GitHub-зеркало и канал-инбокс."

## Diagnostics

```bash
# Bot logs
ssh "$SSH_USER@$VPS_IP" docker logs --tail 200 soroka-bot

# Setup wizard state
ssh "$SSH_USER@$VPS_IP" \
  "sqlite3 /opt/soroka/data/soroka.db 'SELECT setup_step FROM owners'"

# Note count
ssh "$SSH_USER@$VPS_IP" \
  "sqlite3 /opt/soroka/data/soroka.db 'SELECT count(*) FROM notes'"
```

## Updating

```bash
./bin/update "$VPS_IP" "$SSH_USER"
```

## Architecture, in 60 seconds

- Single Docker container (`soroka-bot`) running `python -m src.bot.main`.
- SQLite database at `/opt/soroka/data/soroka.db` (FTS5 + sqlite-vec).
- All user secrets except `TELEGRAM_BOT_TOKEN` and `OWNER_TELEGRAM_ID` live in
  the `owners` table, populated through `/start` in Telegram.
- The MCP server (`src/mcp/server.py`) is invoked on demand via
  `docker exec -i soroka-bot python -m src.mcp.server` — wrapped by
  `/usr/local/bin/soroka-mcp` for SSH-stdio access.

## Files you must NOT touch on the VPS

- `/opt/soroka/.env` — installer wrote it, leave it alone
- `/opt/soroka/data/soroka.db` — SQLite database
- `/opt/soroka/data/attachments/` — user files

If `/start` fails, ask the user to run `/cancel` and `/start` again.
```

- [ ] **Step 2: Commit**

```bash
git add AGENTS.md
git commit -m "docs: AGENTS.md deployment protocol for AI agents"
```

---

### Task 45: `README.md`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace placeholder `README.md`**

```markdown
# 🐦 Soroka

Telegram-бот, который превращает «Избранное» в персональную базу знаний.
Ты форвардишь в приватный канал что угодно — голос, ссылки, статьи, документы.
Soroka индексирует и хранит. Чтобы найти — пишешь боту в DM.
Возвращает оригинальные ссылки и файлы, не пересказы.

## Что нужно

1. **VPS** — Ubuntu 22.04+, 1GB RAM, EU локация, доступ по SSH-ключу.
2. **Telegram-бот** — создай у [@BotFather](https://t.me/BotFather), сохрани токен.
3. **Свой Telegram ID** — узнай у [@userinfobot](https://t.me/userinfobot).

После установки бот сам спросит ключи (бесплатные/дешёвые):
- [Jina](https://jina.ai/embeddings) — эмбеддинги (free tier 1M токенов)
- [Deepgram](https://deepgram.com) — голос → текст ($200 free)
- [OpenRouter](https://openrouter.ai/keys) — LLM (есть `:free` модели)
- [GitHub Personal Access Token](https://github.com/settings/tokens/new) — для бэкапов

## Установка

```bash
git clone https://github.com/YOUR_USER/soroka.git
cd soroka
./bin/install
```

Скрипт интерактивный — задаст IP VPS, SSH-юзера, токен бота, твой Telegram ID, и
сам развернёт бота на сервере. **Никаких файлов на сервере вручную ты не редактируешь.**

После завершения открой Telegram и отправь своему боту `/start` — мастер
проведёт через 6 шагов настройки в чате.

## Команды бота

- `/start` — мастер настройки (запускается один раз; повтор возобновляет с прерванного шага)
- `/help` — справка
- `/status` — текущие настройки и статистика
- `/setjina`, `/setdeepgram`, `/setkey` — заменить отдельный ключ
- `/models` — выбрать основную/fallback LLM
- `/setgithub` — заменить GitHub-токен и репо-зеркало
- `/setvps` — задать IP/юзера VPS (используется в `/mcp`)
- `/setinbox` — сменить канал-инбокс
- `/export` — выгрузить базу архивом
- `/mcp` — конфиг для Claude Desktop (MCP-сервер по SSH stdio)
- `/cancel` — прервать мастер/диалог

## Архитектура

```
Канал «Избранное 2» ──→ Бот на VPS ──→ SQLite (FTS5 + sqlite-vec)
DM с ботом         ──↗               ↑
                                      │
Claude Desktop через MCP-stdio ──SSH──┘
```

Подробности — `docs/specs/2026-04-30-design.md`.

## Обновление

```bash
./bin/update <vps-ip>
```

## Резервное копирование

При `/export` архив до 50MB бот отдаёт прямо в Telegram. Если больше —
заливает GitHub Release в твой приватный репо `username/soroka-data` и
присылает ссылку.

## Для AI-агентов

См. `AGENTS.md` — там точный протокол развёртывания через флаги.

## Лицензия

MIT.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: full README with setup, commands, and architecture"
```

---

## Phase 12 — End-to-end smoke test

### Task 46: Smoke test for the full ingest+search flow

**Files:**
- Create: `tests/test_e2e.py`

- [ ] **Step 1: Write the smoke test**

```python
# tests/test_e2e.py
import pytest
from unittest.mock import AsyncMock
from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner, update_owner_field
from src.core.ingest import ingest_text
from src.core.search import hybrid_search, rerank
from src.core.intent import parse_intent


@pytest.mark.asyncio
async def test_ingest_then_search_finds_note(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    update_owner_field(conn, 1, "primary_model", "x")
    update_owner_field(conn, 1, "fallback_model", "y")

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[1.0] + [0.0] * 1023)
    fake_or = AsyncMock()
    fake_or.complete = AsyncMock(side_effect=[
        '{"clean_query": "паста", "kind": null}',
        '[1]',
    ])

    await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-100, tg_message_id=10,
        text="рецепт пасты карбонара", caption=None, created_at=1,
    )

    intent = await parse_intent(fake_or, primary="x", fallback="y",
                                 query="что я сохранял про пасту")
    candidates = await hybrid_search(
        conn, jina=fake_jina, owner_id=1,
        clean_query=intent.clean_query, kind=intent.kind, limit=15,
    )
    reranked = await rerank(
        fake_or, primary="x", fallback="y",
        query=intent.clean_query, candidates=candidates, top_k=5,
    )
    assert any("карбонара" in n.content for n in reranked)
```

- [ ] **Step 2: Run, PASS**

Run: `pytest tests/test_e2e.py -v`

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test: end-to-end smoke (ingest → intent → search → rerank)"
```

---

### Task 47: Final integration check

- [ ] **Step 1: Run full test suite**

```bash
pytest -v
```

Expected: all PASS (OCR test may SKIP if tesseract not in local env).

- [ ] **Step 2: Build the Docker image**

```bash
docker compose build
```

Expected: successful build.

- [ ] **Step 3: Manual deployment dry-run on a real VPS**

(out of scope for automated checks — produces a real environment)

- [ ] **Step 4: Tag MVP**

```bash
git tag -a v0.1.0 -m "Soroka MVP"
```

---

## Self-review notes

**Spec coverage map:**

| Spec section | Tasks |
|-------------|------|
| §1 принципы | architecture inherent in code organization |
| §2.1 сохранение | Tasks 19-31 (extractors + channel handler) |
| §2.2 поиск | Tasks 32-36 (intent + hybrid + rerank + DM handler) |
| §2.3 команды | Tasks 37-41 |
| §3.1 структура | Task 1 + each subsequent file in tasks |
| §3.2 схема БД | Task 3 |
| §3.3 ingest pipeline | Tasks 27-31 |
| §3.4 search pipeline | Tasks 32-34, 36 |
| §3.5 export | Tasks 40-41 |
| §3.6 MCP | Task 42 |
| §3.7 OpenRouter models | Tasks 11, 16 |
| §3.8 онбординг | Tasks 13, 15-18 |
| §4 stack | Task 1 (pyproject.toml) |
| §5 секреты | Tasks 1, 8, 13 |
| §6 deployment | Tasks 1, 43, 44, 45 |
| §9 готовность | covered by Task 47 manual checks + automated tests |

**Known follow-ups outside MVP** (not blocking the plan):
- Long-document chunking strategy (spec §7)
- Retry/backoff for Jina/Deepgram (spec §7)
- Intent prompt iteration based on real user queries

---

**Plan complete.** Saved to `docs/plans/2026-04-30-soroka-mvp.md`.
