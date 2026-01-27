from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Dict, Any


class FileMeta(BaseModel):
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    storage_key: Optional[str] = None
    size_bytes: Optional[int] = None


class WeComInbound(BaseModel):
    """Normalized inbound message from WeCom Bridge."""

    msg_id: str
    chat_id: str
    user_id: str
    user_name: str
    msg_time: int
    msg_type: Literal["text", "image", "file", "mixed"]
    text: Optional[str] = None
    file: Optional[FileMeta] = None
    mentions: List[str] = Field(default_factory=list)
    quoted_msg_id: Optional[str] = None

    # Raw metadata for traceability
    raw_payload: Optional[Dict[str, Any]] = None


class OpenCodePart(BaseModel):
    """SDK v2 compliant message part."""

    type: Literal["text", "file", "agent", "subtask"]
    text: Optional[str] = None
    mime: Optional[str] = None
    url: Optional[str] = None
    filename: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    # Optional timing for backfills
    time: Optional[Dict[str, int]] = None  # e.g., {"start": 1705555555}


class BackfillChunk(BaseModel):
    """Aggregate chunk for historical message synchronization."""

    chunk_id: str
    range_start: int
    range_end: int
    message_count: int
    text: str  # The "Transcript Backfill" block
    metadata: Optional[Dict[str, Any]] = None
