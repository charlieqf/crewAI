"""
ChatMessage - Data model for storing chat messages.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """Data model for a chat message."""

    message_id: str = Field(..., description="Unique message identifier")
    chat_id: str = Field(..., description="Chat/Group identifier")
    sender_id: str = Field(..., description="Sender's user ID")
    sender_name: str = Field(..., description="Sender's display name")
    content: str = Field(..., description="Message content")
    timestamp: datetime = Field(
        default_factory=datetime.now, description="Message timestamp"
    )
    message_type: str = Field(
        default="text", description="Message type (text, image, etc.)"
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
