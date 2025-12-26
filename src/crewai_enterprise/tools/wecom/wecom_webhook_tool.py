"""
WeComWebhookTool - Send messages to WeCom group via Webhook.

This tool uses WeCom's Webhook API to send messages directly to groups,
which is simpler than the application message API.
"""

from __future__ import annotations

import logging

import requests
from pydantic import BaseModel, Field

from crewai.tools import BaseTool


logger = logging.getLogger(__name__)


class WeComWebhookError(Exception):
    """Raised when sending webhook message fails."""

    pass


class WeComWebhookToolInput(BaseModel):
    """Input schema for WeComWebhookTool."""

    content: str = Field(..., description="The message content to send.")
    msg_type: str = Field(
        default="text", description="Message type: 'text' or 'markdown'."
    )


class WeComWebhookTool(BaseTool):
    """A tool to send messages to WeCom groups via Webhook."""

    name: str = "WeCom Webhook Tool"
    description: str = "Send messages to WeCom groups via Webhook URL."
    args_schema: type[BaseModel] = WeComWebhookToolInput

    # Configuration
    webhook_url: str = Field(..., description="WeCom Webhook URL")

    def _run(self, content: str, msg_type: str = "text") -> str:
        """Execute the tool logic to send a message via webhook."""
        if msg_type == "text":
            payload = {"msgtype": "text", "text": {"content": content}}
        elif msg_type == "markdown":
            payload = {"msgtype": "markdown", "markdown": {"content": content}}
        else:
            raise WeComWebhookError(f"Unsupported message type: {msg_type}")

        try:
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.RequestException as e:
            raise WeComWebhookError(f"Network error sending webhook: {e}") from e

        if data.get("errcode") == 0:
            logger.info(f"Webhook message sent successfully")
            return "Message sent successfully"
        else:
            raise WeComWebhookError(
                f"Webhook error - Code: {data.get('errcode')}, Msg: {data.get('errmsg')}"
            )


# Convenience function for quick sending
def send_webhook_message(webhook_url: str, content: str, msg_type: str = "text") -> str:
    """Send a message to WeCom group via webhook without creating a tool instance."""
    tool = WeComWebhookTool(webhook_url=webhook_url)
    return tool._run(content=content, msg_type=msg_type)
