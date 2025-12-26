"""
WeCom Callback Server.

FastAPI server to receive and process Enterprise WeChat callback messages.
Supports multiple AI bots (OpenAI GPT, Gemini, Grok) for group chat.

Refactored: Processing logic extracted to handlers package for better maintainability.
"""

from __future__ import annotations

import logging
import os

import defusedxml.ElementTree as ET

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from src.crewai_enterprise.utils.wecom_crypto import WeComCrypto, WeComCryptoError
from src.crewai_enterprise.utils.wecom_message import (
    WeComMessage,
    WeComMessageParseError,
    parse_message,
)

# Import handlers from the new modular package
from src.crewai_enterprise.server.handlers import (
    BOT_CONFIG,
    detect_bot_type,
    is_clear_command,
    process_text_message,
    handle_clear_command,
    process_file_message,
)


logger = logging.getLogger(__name__)


class WeComCallbackConfigError(Exception):
    """Raised when required configuration is missing."""


def get_required_env(key: str) -> str:
    """Get a required environment variable, fail fast if missing."""
    value = os.getenv(key)
    if not value:
        raise WeComCallbackConfigError(
            f"Required environment variable '{key}' is not set"
        )
    return value


def get_optional_env(key: str, default: str = "") -> str:
    """Get an optional environment variable."""
    return os.getenv(key, default)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""

    app = FastAPI(
        title="WeCom Callback Server",
        description="Receives and processes Enterprise WeChat callback messages for CrewAI agents.",
        version="0.3.0",  # Version bump for refactored structure
    )

    # Lazy initialization for crypto
    _crypto: WeComCrypto | None = None

    def get_crypto() -> WeComCrypto:
        nonlocal _crypto
        if _crypto is None:
            token = get_required_env("WECOM_TOKEN")
            encoding_aes_key = get_required_env("WECOM_ENCODING_AES_KEY")
            corp_id = get_required_env("WECOM_CORP_ID")
            _crypto = WeComCrypto(token, encoding_aes_key, corp_id)
        return _crypto

    @app.get("/wecom/callback", response_class=PlainTextResponse)
    async def verify_url(
        msg_signature: str = Query(..., description="Message signature"),
        timestamp: str = Query(..., description="Timestamp"),
        nonce: str = Query(..., description="Nonce"),
        echostr: str = Query(..., description="Echo string to return"),
    ) -> str:
        """URL verification endpoint for WeCom callback configuration."""
        crypto = get_crypto()

        if not crypto.verify_signature(msg_signature, timestamp, nonce, echostr):
            raise HTTPException(status_code=403, detail="Invalid signature")

        try:
            return crypto.decrypt_message(echostr)
        except WeComCryptoError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.post("/wecom/callback")
    async def receive_message(
        request: Request,
        background_tasks: BackgroundTasks,
        msg_signature: str = Query(..., description="Message signature"),
        timestamp: str = Query(..., description="Timestamp"),
        nonce: str = Query(..., description="Nonce"),
    ) -> dict[str, str | bool | None]:
        """
        Receive and process callback messages from WeCom.
        Routes to appropriate AI bot and sends reply via background task.
        """
        crypto = get_crypto()

        # Read the raw XML body
        body = await request.body()
        xml_body = body.decode("utf-8")

        # Extract encrypted content for signature verification
        try:
            root = ET.fromstring(xml_body)
            encrypt_element = root.find("Encrypt")
            encrypt_content = (
                encrypt_element.text if encrypt_element is not None else ""
            )
        except ET.ParseError as e:
            raise HTTPException(status_code=400, detail="Invalid XML body") from e

        # Verify signature
        if not crypto.verify_signature(
            msg_signature, timestamp, nonce, encrypt_content
        ):
            raise HTTPException(status_code=403, detail="Invalid signature")

        # Decrypt the message
        try:
            decrypted_xml = crypto.decrypt_callback_body(xml_body)
        except WeComCryptoError as e:
            raise HTTPException(
                status_code=400, detail=f"Decryption failed: {e}"
            ) from e

        # Parse the message
        try:
            message: WeComMessage = parse_message(decrypted_xml)
        except WeComMessageParseError as e:
            raise HTTPException(
                status_code=400, detail=f"Message parse failed: {e}"
            ) from e

        logger.info(
            f"[RECV] msg_id={message.msg_id} type={message.msg_type} "
            f"from={message.from_user_name} agent={message.agent_id} "
            f"content={repr(message.content[:50] if message.content else '[media]')}..."
        )

        # Determine chat_id for context isolation
        chat_id = message.agent_id or message.to_user_name or "default"
        user_name = message.from_user_name or "用户"
        content = message.content or ""
        bot_type = detect_bot_type(content)

        logger.debug(f"[ROUTE] chat_id={chat_id} user={user_name} bot_type={bot_type}")

        # Get webhook URL for bot
        config = BOT_CONFIG.get(bot_type, BOT_CONFIG["gpt"])
        webhook_url = get_optional_env(config["webhook_env"])

        if not webhook_url:
            logger.warning(
                f"[NO_WEBHOOK] bot_type={bot_type} env={config['webhook_env']} - message dropped"
            )
            return {
                "status": "no_webhook",
                "from": message.from_user_name,
                "type": message.msg_type,
            }

        # Route message to appropriate handler
        if message.msg_type == "text" and content:
            # Check for clear command
            if is_clear_command(content):
                logger.info(f"[CLEAR] chat_id={chat_id} user={user_name}")
                background_tasks.add_task(
                    handle_clear_command,
                    chat_id,
                    user_name,
                    webhook_url,
                )
                return {
                    "status": "clearing",
                    "chat_id": chat_id,
                    "from": message.from_user_name,
                }

            # Normal text message
            logger.info(
                f"[PROCESS] msg_id={message.msg_id} bot={bot_type} chat={chat_id}"
            )
            background_tasks.add_task(
                process_text_message,
                bot_type,
                chat_id,
                user_name,
                content,
                webhook_url,
                message.msg_id,  # Pass WeCom MsgId for deduplication
            )

        elif message.has_media:
            # File/media message
            logger.info(
                f"[FILE] msg_id={message.msg_id} type={message.msg_type} "
                f"media_id={message.media_id} filename={message.filename}"
            )
            background_tasks.add_task(
                process_file_message,
                bot_type,
                chat_id,
                message,
                user_name,
                webhook_url,
            )
        else:
            logger.debug(
                f"[SKIP] msg_id={message.msg_id} type={message.msg_type} - no handler"
            )

        # Always acknowledge receipt quickly
        return {
            "status": "received",
            "from": message.from_user_name,
            "type": message.msg_type,
            "has_media": message.has_media,
            "routed_to": bot_type,
        }

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "healthy", "service": "wecom-callback", "version": "0.3.0"}

    return app


# Initialize logging before app creation
from src.crewai_enterprise.server.logging_config import setup_logging

setup_logging()

# Create the app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
