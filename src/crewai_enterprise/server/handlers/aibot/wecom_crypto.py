from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

import requests
from Crypto.Cipher import AES

from src.crewai_enterprise.utils.wecom_json_crypto import WXBizJsonMsgCrypt

from .config import BOT_CONFIGS

logger = logging.getLogger(__name__)


def _generate_stream_id() -> str:
    """Generate a unique stream ID for task tracking."""
    import random
    import string

    return "".join(random.choices(string.ascii_letters + string.digits, k=16))


def _sanitize_text(text: str) -> str:
    """Remove hidden/invisible characters from text that may come from WeCom copy-paste."""
    if not text:
        return text

    invisible_chars = [
        "\u200b",  # Zero-width space
        "\u200c",  # Zero-width non-joiner
        "\u200d",  # Zero-width joiner
        "\ufeff",  # BOM / Zero-width no-break space
        "\u00a0",  # Non-breaking space (replace with regular space)
        "\u3000",  # Ideographic space (full-width space)
        "\u2028",  # Line separator
        "\u2029",  # Paragraph separator
    ]

    result = text
    for char in invisible_chars:
        result = result.replace(char, " " if char in ["\u00a0", "\u3000"] else "")

    result = " ".join(result.split())
    return result


def _get_bot_crypto(bot_type: str) -> WXBizJsonMsgCrypt:
    """Get WXBizJsonMsgCrypt instance for a specific bot."""
    config = BOT_CONFIGS.get(bot_type)
    if not config:
        raise ValueError(f"Unknown bot type: {bot_type}")

    token = os.getenv(config["token_env"], "")
    aes_key = os.getenv(config["aes_key_env"], "")

    if not token or not aes_key:
        raise ValueError(
            f"Missing configuration for {bot_type}: "
            f"set {config['token_env']} and {config['aes_key_env']}"
        )

    return WXBizJsonMsgCrypt(token, aes_key, "")


def _get_bot_aes_key(bot_type: str) -> str:
    """Get the EncodingAESKey for a specific bot."""
    config = BOT_CONFIGS.get(bot_type)
    if not config:
        raise ValueError(f"Unknown bot type: {bot_type}")
    return os.getenv(config["aes_key_env"], "")


def _decrypt_media(media_url: str, aes_key_base64: str) -> tuple[bool, bytes | str]:
    """Download and decrypt encrypted media (image/file) from WeCom."""
    try:
        logger.info(f"[MEDIA] Downloading encrypted media: {media_url[:80]}...")
        response = requests.get(media_url, timeout=60)
        response.raise_for_status()
        encrypted_data = response.content
        logger.info(f"[MEDIA] Downloaded {len(encrypted_data)} bytes")

        if not aes_key_base64:
            raise ValueError("AES key is empty")

        aes_key = base64.b64decode(aes_key_base64 + "=" * (-len(aes_key_base64) % 4))
        if len(aes_key) != 32:
            raise ValueError(f"Invalid AES key length: expected 32, got {len(aes_key)}")

        iv = aes_key[:16]
        cipher = AES.new(aes_key, AES.MODE_CBC, iv)
        decrypted_data = cipher.decrypt(encrypted_data)

        pad_len = decrypted_data[-1]
        if pad_len > 32:
            raise ValueError(f"Invalid padding length: {pad_len}")

        decrypted_data = decrypted_data[:-pad_len]
        logger.info(f"[MEDIA] Decrypted to {len(decrypted_data)} bytes")

        return True, decrypted_data

    except requests.exceptions.RequestException as e:
        error_msg = f"Media download failed: {e}"
        logger.error(f"[MEDIA] {error_msg}")
        return False, error_msg

    except ValueError as e:
        error_msg = f"Decryption error: {e}"
        logger.error(f"[MEDIA] {error_msg}")
        return False, error_msg

    except Exception as e:
        error_msg = f"Media processing error: {e}"
        logger.error(f"[MEDIA] {error_msg}")
        return False, error_msg


def _make_text_stream(stream_id: str, content: str, finish: bool) -> str:
    """Create a text stream response message."""
    return json.dumps(
        {
            "msgtype": "stream",
            "stream": {"id": stream_id, "finish": finish, "content": content},
        },
        ensure_ascii=False,
    )


def _encrypt_response(bot_type: str, stream_json: str, nonce: str, timestamp: str) -> str:
    """Encrypt response message for WeCom."""
    crypto = _get_bot_crypto(bot_type)
    ret, encrypted = crypto.EncryptMsg(stream_json, nonce, timestamp)
    if ret != 0:
        raise ValueError(f"Encryption failed with error code: {ret}")
    return encrypted


__all__ = [
    "_generate_stream_id",
    "_sanitize_text",
    "_get_bot_crypto",
    "_get_bot_aes_key",
    "_decrypt_media",
    "_make_text_stream",
    "_encrypt_response",
]
