"""
WeCom Message Parsing Utilities.

Parses XML messages received from Enterprise WeChat callbacks.
Supports text, image, voice, video, and file messages.
"""

from __future__ import annotations

import defusedxml.ElementTree as ET
from dataclasses import dataclass


class WeComMessageParseError(Exception):
    """Raised when message parsing fails."""

    pass


@dataclass
class WeComMessage:
    """Represents a parsed WeCom message."""

    to_user_name: str
    from_user_name: str
    create_time: int
    msg_type: str
    content: str | None = None
    msg_id: str | None = None
    agent_id: str | None = None

    # File/media fields
    media_id: str | None = None
    pic_url: str | None = None  # For image messages
    format: str | None = None  # For voice messages (amr, speex)
    thumb_media_id: str | None = None  # For video messages

    # File message specific
    title: str | None = None  # Filename for file messages
    description: str | None = None

    # Event fields
    event: str | None = None
    event_key: str | None = None

    @property
    def is_text(self) -> bool:
        return self.msg_type == "text"

    @property
    def is_image(self) -> bool:
        return self.msg_type == "image"

    @property
    def is_voice(self) -> bool:
        return self.msg_type == "voice"

    @property
    def is_video(self) -> bool:
        return self.msg_type == "video"

    @property
    def is_file(self) -> bool:
        return self.msg_type == "file"

    @property
    def is_event(self) -> bool:
        return self.msg_type == "event"

    @property
    def has_media(self) -> bool:
        """Check if message contains downloadable media."""
        return self.media_id is not None

    @property
    def filename(self) -> str | None:
        """Get filename for file messages."""
        return self.title


def parse_message(xml_content: str) -> WeComMessage:
    """
    Parse a decrypted WeCom message XML.

    Supports message types: text, image, voice, video, file, event

    Args:
        xml_content: The decrypted XML content.

    Returns:
        A WeComMessage object with parsed fields.
    """
    try:
        root = ET.fromstring(xml_content)

        to_user = _get_text(root, "ToUserName")
        from_user = _get_text(root, "FromUserName")
        create_time_str = _get_text(root, "CreateTime", "0")
        create_time = int(create_time_str) if create_time_str else 0
        msg_type = _get_text(root, "MsgType")

        if not to_user or not from_user or not msg_type:
            raise WeComMessageParseError("Missing required fields in message XML")

        # Common fields
        msg = WeComMessage(
            to_user_name=to_user,
            from_user_name=from_user,
            create_time=create_time,
            msg_type=msg_type,
            msg_id=_get_text(root, "MsgId"),
            agent_id=_get_text(root, "AgentID"),
        )

        # Parse type-specific fields
        if msg_type == "text":
            msg.content = _get_text(root, "Content")

        elif msg_type == "image":
            msg.pic_url = _get_text(root, "PicUrl")
            msg.media_id = _get_text(root, "MediaId")

        elif msg_type == "voice":
            msg.media_id = _get_text(root, "MediaId")
            msg.format = _get_text(root, "Format")

        elif msg_type == "video":
            msg.media_id = _get_text(root, "MediaId")
            msg.thumb_media_id = _get_text(root, "ThumbMediaId")

        elif msg_type == "file":
            msg.media_id = _get_text(root, "MediaId")
            msg.title = _get_text(root, "Title")
            msg.description = _get_text(root, "Description")

        elif msg_type == "event":
            msg.event = _get_text(root, "Event")
            msg.event_key = _get_text(root, "EventKey")

        return msg

    except ET.ParseError as e:
        raise WeComMessageParseError(f"Failed to parse message XML: {e}") from e


def _get_text(root: ET.Element, tag: str, default: str | None = None) -> str | None:
    """Helper to get text content of an XML element."""
    element = root.find(tag)
    if element is not None and element.text:
        return element.text
    return default
