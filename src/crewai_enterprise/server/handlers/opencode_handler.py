import logging
import os
from src.crewai_enterprise.utils.wecom_message import WeComMessage
from src.crewai_enterprise.tools.wecom.wecom_webhook_tool import send_webhook_message
from src.crewai_enterprise.server.opencode_bridge import OpenCodeBridge
from src.crewai_enterprise.server.models.opencode import WeComInbound, FileMeta
from src.crewai_enterprise.server.handlers.opencode_commands import (
    handle_opencode_command,
)
from src.crewai_enterprise.server.handlers.opencode_aggregator import StatusAggregator

logger = logging.getLogger(__name__)

# Single instance of the bridge
_bridge: OpenCodeBridge | None = None


def get_bridge() -> OpenCodeBridge:
    global _bridge
    if _bridge is None:
        opencode_url = os.getenv("OPENCODE_URL", "http://localhost:4096")
        history_db = os.getenv(
            "HISTORY_DB_PATH", "/var/lib/wecom-callback/chat_history.db"
        )
        storage_db = os.getenv(
            "STORAGE_DB_PATH", "/var/lib/wecom-callback/chat_storage.db"
        )
        default_repo = os.getenv("DEFAULT_REPO_PATH", "/opt/oh-my-opencode")
        api_key = os.getenv("OPENCODE_API_KEY")

        _bridge = OpenCodeBridge(
            opencode_url=opencode_url,
            history_db=history_db,
            storage_db=storage_db,
            api_key=api_key,
            default_repo_path=default_repo,
        )
        logger.info(f"[OPENCODE] Bridge initialized: {opencode_url}")
    return _bridge


async def process_opencode_message(
    chat_id: str,
    user_name: str,
    content: str,
    webhook_url: str,
    message: WeComMessage,
) -> None:
    """Process message routed to OpenCode bot."""
    bridge = get_bridge()

    # 1. Normalize to WeComInbound
    inbound = WeComInbound(
        msg_id=message.msg_id,
        chat_id=chat_id,
        user_id=message.from_user_id or "unknown",
        user_name=user_name,
        msg_time=int(message.create_time or 0),
        msg_type="mixed"
        if message.has_media and content
        else (
            message.msg_type
            if message.msg_type in ["text", "image", "file"]
            else "text"
        ),
        text=content,
        mentions=message.mentions if hasattr(message, "mentions") else [],
        quoted_msg_id=getattr(message, "quoted_msg_id", None),
    )

    # Handle files if present
    if message.has_media:
        inbound.file = FileMeta(
            filename=message.filename,
            mime_type=getattr(message, "mime_type", None),
            storage_key=getattr(message, "storage_key", None),
        )

    logger.info(f"[OPENCODE] Processing message {message.msg_id} from {user_name}")

    # 2. Intercept Commands
    cmd_result = handle_opencode_command(content, chat_id, message.from_user_id)
    response_text = ""  # Initialize response_text
    if cmd_result:
        if cmd_result["type"] == "response":
            response_text = cmd_result["content"]
        elif cmd_result["type"] == "sdk_command":
            try:
                # [FIX] Finding 1: Use session_uuid instead of chat_id for command routing
                session_uuid = bridge.session_store.get_session_id(chat_id)
                res = bridge.client.send_command(
                    session_id=session_uuid,
                    command=cmd_result["command"],
                    arguments=cmd_result["arguments"],
                    message_id=message.msg_id,
                )
                response_text = res.json().get("content", "Command executed.")
            except Exception as e:
                response_text = f"Command failed: {e}"
        elif cmd_result["type"] == "bridge_action":
            # Handle reset or config locally in the bridge
            if cmd_result["action"] == "reset_session":
                # True Reset: Rotate Session UUID + Jump watermark to NOW
                from datetime import datetime, timezone, timedelta

                now_str = datetime.now(timezone(timedelta(hours=8))).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                # Sync first so the reset watermark matches the true archive head.
                bridge._force_archive_sync()
                max_seq = bridge.get_chat_max_seq(chat_id)
                bridge._update_last_sync_time(chat_id, now_str, "", max_seq)

                # Rotate session UUID for true context isolation in OpenCode
                new_session_id = bridge.session_store.rotate_session(chat_id)

                response_text = f"Session context has been reset. New session started: `{new_session_id[:8]}`."
            elif cmd_result["action"] == "show_config":
                # Reflect actual mapping from the bridge instance
                repo = bridge.default_repo_path
                response_text = f"**Current Configuration:**\n- Session: `{chat_id}`\n- Repo: `{repo}`"
            else:
                response_text = "Action not implemented."
    else:
        # 3. Handle mention (Streaming Path)
        aggregator = StatusAggregator(throttle_seconds=10)  # Roadmap says 10s
        response_text = ""
        last_status_msg = ""

        async for event in bridge.handle_mention_stream(inbound):
            event_type = event.get("type")
            if event_type == "text":
                response_text += event.get("content", "")
            elif event_type == "error":
                error_msg = event.get("content") or "Unknown streaming error"
                response_text += f"\n\n[ERROR] {error_msg}"

            # Aggregate status updates
            status_update = aggregator.process_event(event)
            if status_update and status_update != last_status_msg:
                # Progress Update: Send a new message or update (if WeCom supports it)
                # Webhook only supports new message, but it gives user sense of "Working"
                try:
                    send_webhook_message(
                        webhook_url, f"@{user_name}\n{status_update}", msg_type="text"
                    )
                    last_status_msg = status_update
                except Exception as e:
                    logger.warning(f"[OPENCODE] Failed to send status update: {e}")

        # If no result content, show error
        if not response_text:
            response_text = "OpenCode did not return a text response."

    # 4. Send response back to WeCom
    try:
        reply = f"@{user_name} \n\n{response_text}"
        send_webhook_message(webhook_url, reply, msg_type="text")
        logger.info(f"[OPENCODE] Response sent for {message.msg_id}")
    except Exception as e:
        logger.error(f"[OPENCODE] Failed to send webhook: {e}")
