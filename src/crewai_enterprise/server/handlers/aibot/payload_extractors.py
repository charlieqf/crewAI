from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _extract_msg_id(data: dict) -> str | None:
    """Extract message ID from WeCom payload for dedup."""
    for key in ["msgid", "msg_id", "MsgId", "message_id"]:
        if key in data:
            return str(data[key])

    if "msg" in data and isinstance(data["msg"], dict):
        return data["msg"].get("msgid")

    for nested_key in ["text", "image", "voice", "file", "link"]:
        if nested_key in data and isinstance(data[nested_key], dict):
            nested = data[nested_key]
            for key in ["msgid", "msg_id", "MsgId"]:
                if key in nested:
                    return str(nested[key])

    nested_info = {
        k: list(v.keys())[:5] if isinstance(v, dict) else type(v).__name__
        for k, v in list(data.items())[:8]
    }
    logger.debug(f"[AIBOT_MSGID] Could not extract msgid, structure: {nested_info}")
    return None


def _extract_chat_id(data: dict, user_id: str) -> str:
    """Extract chat/group ID from WeCom payload."""
    for key in ["chat_id", "chatid", "ChatId", "roomid", "room_id", "groupid"]:
        if key in data and data[key]:
            return str(data[key])

    if "chat" in data and isinstance(data["chat"], dict):
        chat_data = data["chat"]
        for key in ["id", "chat_id", "chatid"]:
            if key in chat_data and chat_data[key]:
                return str(chat_data[key])

    return user_id


def _extract_quote_content(data: dict) -> tuple[str | None, str | None]:
    """Extract quoted message content and ID from WeCom payload."""
    if "quote" in data and isinstance(data["quote"], dict):
        quote_data = data["quote"]
        msgid = quote_data.get("msgid") or quote_data.get("msg_id") or quote_data.get("MsgId")
        for key in ["content", "text", "Content", "Text"]:
            if key in quote_data and quote_data[key]:
                return str(quote_data[key]).strip(), msgid
        if "msgtype" in quote_data:
            msgtype = quote_data["msgtype"]
            if msgtype == "text" and "text" in quote_data:
                text_obj = quote_data["text"]
                if isinstance(text_obj, dict) and "content" in text_obj:
                    msgid = quote_data.get("msgid") or quote_data.get("msg_id") or quote_data.get("MsgId")
                    return str(text_obj["content"]).strip(), msgid

    text_data = data.get("text", {})
    if isinstance(text_data, dict) and "quote" in text_data:
        quote_in_text = text_data["quote"]
        if isinstance(quote_in_text, dict):
            msgid = quote_in_text.get("msgid") or quote_in_text.get("msg_id") or quote_in_text.get("MsgId")
            for key in ["content", "text"]:
                if key in quote_in_text and quote_in_text[key]:
                    return str(quote_in_text[key]).strip(), msgid
        elif isinstance(quote_in_text, str):
            return quote_in_text.strip(), None

    if "reference" in data and isinstance(data["reference"], dict):
        ref = data["reference"]
        msgid = ref.get("msgid") or ref.get("msg_id") or ref.get("MsgId")
        for key in ["content", "text", "Content", "Text"]:
            if key in ref and ref[key]:
                return str(ref[key]).strip(), msgid

    return None, None


def _extract_text_from_mixed(data: dict) -> str:
    """Extract text content from a mixed (image+text) message."""
    text_parts = []
    msg_items = data.get("msg_item", data.get("mixed", {}).get("msg_item", []))
    if isinstance(msg_items, list):
        for item in msg_items:
            if isinstance(item, dict):
                item_type = item.get("msgtype", item.get("type", ""))
                if item_type == "text":
                    text_obj = item.get("text", {})
                    if isinstance(text_obj, dict):
                        content = text_obj.get("content", "")
                        if content:
                            text_parts.append(content)
                    elif isinstance(text_obj, str):
                        text_parts.append(text_obj)

    if not text_parts:
        text_data = data.get("text", {})
        if isinstance(text_data, dict):
            content = text_data.get("content", "")
            if content:
                text_parts.append(content)
        elif isinstance(text_data, str):
            text_parts.append(text_data)

    return " ".join(text_parts).strip()


def _has_image_in_mixed(data: dict) -> bool:
    """Check if mixed message contains image content."""
    msg_items = data.get("msg_item", data.get("mixed", {}).get("msg_item", []))
    if isinstance(msg_items, list):
        for item in msg_items:
            if isinstance(item, dict):
                item_type = item.get("msgtype", item.get("type", ""))
                if item_type == "image":
                    return True
    return False


def _extract_image_urls_from_mixed(data: dict) -> list[str]:
    """Extract image URLs from mixed message or image message."""
    urls = []
    msg_items = data.get("msg_item", data.get("mixed", {}).get("msg_item", []))
    if isinstance(msg_items, list):
        for item in msg_items:
            if isinstance(item, dict):
                item_type = item.get("msgtype", item.get("type", ""))
                if item_type == "image":
                    image_data = item.get("image", {})
                    url = image_data.get("url", image_data.get("pic_url", ""))
                    if url:
                        urls.append(url)

    if not urls:
        image_data = data.get("image", {})
        url = image_data.get("url", image_data.get("pic_url", ""))
        if url:
            urls.append(url)

    return urls


def _extract_file_info(data: dict) -> tuple[str | None, str, str]:
    """Extract file information (URL, name, mime)."""
    file_data = data.get("file", {})
    file_url = file_data.get("url")
    file_name = file_data.get("filename", "unnamed")
    mime_type = file_data.get("content_type", "application/octet-stream")
    return file_url, file_name, mime_type


__all__ = [
    "_extract_msg_id",
    "_extract_chat_id",
    "_extract_quote_content",
    "_extract_text_from_mixed",
    "_has_image_in_mixed",
    "_extract_image_urls_from_mixed",
    "_extract_file_info",
]
