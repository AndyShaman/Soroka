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
