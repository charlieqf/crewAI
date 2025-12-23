"""
WeComTool - Enterprise WeChat (WeCom) notification tool for CrewAI agents.
"""
from typing import Literal, Optional, Type

import requests
from pydantic import BaseModel, Field, PrivateAttr

from crewai.tools import BaseTool


# --- Custom Exceptions ---
class WeComAuthenticationError(Exception):
    """Raised when WeCom token retrieval fails."""
    pass


class WeComSendError(Exception):
    """Raised when sending a message to WeCom fails."""
    pass


# --- Input Schema ---
class WeComToolInput(BaseModel):
    """Input schema for WeComTool."""
    content: str = Field(..., description="The message content to send.")
    msg_type: Literal["text", "markdown"] = Field(
        default="text", 
        description="The type of message: 'text' or 'markdown'."
    )
    chat_id: Optional[str] = Field(
        None, 
        description="The target group chat ID. If not provided, broadcasts to all users."
    )


# --- Tool Implementation ---
class WeComTool(BaseTool):
    """A tool to send notifications to Enterprise WeChat (WeCom)."""
    
    name: str = "WeCom Notification Tool"
    description: str = "A tool to send notifications to Enterprise WeChat (WeCom) groups or users."
    args_schema: Type[BaseModel] = WeComToolInput
    
    # Configuration: corpid is the enterprise ID, agentid is the app ID within the enterprise
    corp_id: str = Field(..., exclude=True, description="WeCom Enterprise ID")
    agent_id: str = Field(..., exclude=True, description="WeCom Application Agent ID")
    secret: str = Field(..., exclude=True, description="WeCom Application Secret")
    
    # Instance-level token cache to prevent cross-tenant token reuse
    _token_cache: Optional[str] = PrivateAttr(default=None)

    def __init__(self, **data):
        super().__init__(**data)
        self._token_cache = None

    def _get_access_token(self) -> str:
        """Internal method to get/refresh the access token."""
        if self._token_cache:
            return self._token_cache
        
        url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={self.corp_id}&corpsecret={self.secret}"
        
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            raise WeComAuthenticationError(f"Network error fetching WeCom token: {e}") from e
        
        if data.get("errcode") == 0:
            self._token_cache = data.get("access_token")
            return self._token_cache
        else:
            raise WeComAuthenticationError(
                f"WeCom token error - Code: {data.get('errcode')}, Msg: {data.get('errmsg')}"
            )

    def _run(self, content: str, msg_type: str = "text", chat_id: Optional[str] = None) -> str:
        """Execute the tool logic to send a message."""
        token = self._get_access_token()
        url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
        
        # Build payload based on target type
        if chat_id:
            # Send to specific group chat
            payload = {
                "chatid": chat_id,
                "msgtype": msg_type,
                "agentid": self.agent_id,
                msg_type: {"content": content}
            }
        else:
            # Broadcast to all users
            payload = {
                "touser": "@all",
                "msgtype": msg_type,
                "agentid": self.agent_id,
                msg_type: {"content": content}
            }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            raise WeComSendError(f"Network error sending WeCom message: {e}") from e
        
        if data.get("errcode") == 0:
            return "Message sent successfully"
        else:
            raise WeComSendError(
                f"WeCom send error - Code: {data.get('errcode')}, Msg: {data.get('errmsg')}"
            )
