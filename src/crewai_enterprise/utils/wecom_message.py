"""
WeCom Message Parsing Utilities.

Parses XML messages received from Enterprise WeChat callbacks.
"""
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional


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
    content: Optional[str] = None
    msg_id: Optional[str] = None
    agent_id: Optional[str] = None
    
    @property
    def is_text(self) -> bool:
        return self.msg_type == "text"
    
    @property
    def is_event(self) -> bool:
        return self.msg_type == "event"


def parse_message(xml_content: str) -> WeComMessage:
    """
    Parse a decrypted WeCom message XML.
    
    Args:
        xml_content: The decrypted XML content.
    
    Returns:
        A WeComMessage object with parsed fields.
    """
    try:
        root = ET.fromstring(xml_content)
        
        to_user = _get_text(root, "ToUserName")
        from_user = _get_text(root, "FromUserName")
        create_time = int(_get_text(root, "CreateTime", "0"))
        msg_type = _get_text(root, "MsgType")
        
        if not to_user or not from_user or not msg_type:
            raise WeComMessageParseError("Missing required fields in message XML")
        
        return WeComMessage(
            to_user_name=to_user,
            from_user_name=from_user,
            create_time=create_time,
            msg_type=msg_type,
            content=_get_text(root, "Content"),
            msg_id=_get_text(root, "MsgId"),
            agent_id=_get_text(root, "AgentID"),
        )
    except ET.ParseError as e:
        raise WeComMessageParseError(f"Failed to parse message XML: {e}") from e


def _get_text(root: ET.Element, tag: str, default: Optional[str] = None) -> Optional[str]:
    """Helper to get text content of an XML element."""
    element = root.find(tag)
    if element is not None and element.text:
        return element.text
    return default
