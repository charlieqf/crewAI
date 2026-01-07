"""
Archive Callback Handler for WeCom Conversation Archiving.

Handles callbacks from WeCom's conversation archiving API to automatically
collect files from group chats.
"""

import hashlib
import json
import logging
import os
import struct
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from src.crewai_enterprise.utils.chat_context import get_context_manager
from src.crewai_enterprise.utils.storage_manager import get_storage_manager

logger = logging.getLogger(__name__)

# Archive configuration from environment
ARCHIVE_TOKEN = os.getenv("ARCHIVE_TOKEN", "")
ARCHIVE_AES_KEY = os.getenv("ARCHIVE_AES_KEY", "")
WECOM_CORP_ID = os.getenv("WECOM_CORP_ID", os.getenv("CORP_ID", ""))

from src.crewai_enterprise.utils.wecom_json_crypto import WXBizJsonMsgCrypt

# Path to the RSA private key for archive decryption
ARCHIVE_PRIVATE_KEY_PATH = os.getenv("ARCHIVE_RSA_PRIVATE_KEY_PATH", "/opt/wecom-callback/keys/archive_private_key.pem")

router = APIRouter()


def _get_crypto() -> WXBizJsonMsgCrypt:
    """Initialize and return the crypto utility."""
    if not ARCHIVE_TOKEN or not ARCHIVE_AES_KEY or not WECOM_CORP_ID:
        logger.error(f"[ARCHIVE] Configuration missing: TOKEN={bool(ARCHIVE_TOKEN)}, AES_KEY={bool(ARCHIVE_AES_KEY)}, CORP_ID={bool(WECOM_CORP_ID)}")
        raise HTTPException(status_code=500, detail="Archive service configuration error")
    return WXBizJsonMsgCrypt(ARCHIVE_TOKEN, ARCHIVE_AES_KEY, WECOM_CORP_ID)


@router.get("/wecom/archive-callback")
async def archive_callback_verify(
    msg_signature: str = Query(..., description="Message signature"),
    timestamp: str = Query(..., description="Timestamp"),
    nonce: str = Query(..., description="Nonce"),
    echostr: str = Query(..., description="Echo string for verification")
):
    """
    Handle URL verification from WeCom archive service.
    
    When configuring the callback URL in WeCom admin, WeCom will send a GET request
    with these parameters to verify the URL is valid.
    
    We need to:
    1. Verify the signature
    2. Return the echostr
    """
    logger.info(f"[ARCHIVE_VERIFY] Received verification request: timestamp={timestamp}, nonce={nonce}")
    
    try:
        crypto = _get_crypto()
        ret, echostr_decrypted = crypto.VerifyURL(msg_signature, timestamp, nonce, echostr)
        
        if ret != 0:
            logger.error(f"[ARCHIVE_VERIFY] Verification failed with error code {ret}")
            raise HTTPException(status_code=403, detail=f"Verification failed: {ret}")
            
        logger.info("[ARCHIVE_VERIFY] URL verified successfully")
        return Response(content=echostr_decrypted, media_type="text/plain")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[ARCHIVE_VERIFY] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/wecom/archive-callback")
async def archive_callback_message(request: Request, background_tasks: BackgroundTasks):
    """
    Handle message callbacks from WeCom archive service.
    
    This endpoint receives all archived messages from configured group chats.
    We specifically look for file messages to automatically collect them.
    
    Message flow:
    1. User sends file in group chat
    2. WeCom archive service pushes message to this endpoint
    3. We download the file
    4. Upload to Qiniu cloud storage
    5. Save to database (chat_files table)
    6. User can then @gemini to analyze the file
    """
    # Get body for decryption
    body = await request.body()
    logger.info(f"[ARCHIVE_MSG] Raw body: {body.decode('utf-8')[:300]}...")
    
    # Get query parameters
    params = request.query_params
    msg_signature = params.get("msg_signature", "")
    timestamp = params.get("timestamp", "")
    nonce = params.get("nonce", "")
    
    # Get body for decryption
    body = await request.body()
    
    # Decrypt message
    try:
        from src.crewai_enterprise.utils.wecom_crypto import WeComCrypto
        crypto = WeComCrypto(ARCHIVE_TOKEN, ARCHIVE_AES_KEY, WECOM_CORP_ID)
        
        # XML format decryption
        decrypted_xml = crypto.decrypt_callback_body(body.decode("utf-8"))
        logger.info(f"[ARCHIVE_MSG] Decrypted content: {decrypted_xml[:500]}...")
        
        # Parse XML
        import defusedxml.ElementTree as ET
        root = ET.fromstring(decrypted_xml)
        
        # Extract message content (format varies by event type)
        # For archive push, we need to see what's inside.
        message = {"raw_xml": decrypted_xml}
        msg_type_node = root.find("MsgType")
        if msg_type_node is not None:
            message["msgtype"] = msg_type_node.text
            
    except Exception as e:
        logger.error(f"[ARCHIVE_MSG] Decryption failed: {e}")
        return {"status": "ok"}
    
    # Process message
    try:
        # Any callback indicates activity (a message or a notification event).
        # We trigger a background sync to pull the encrypted data.
        background_tasks.add_task(sync_archive_messages)
        logger.info("[ARCHIVE_MSG] Triggered background sync")
    except Exception as e:
        logger.error(f"[ARCHIVE_MSG] Error triggering sync: {e}")
    
    return {"status": "ok"}


from src.crewai_enterprise.utils.wework_finance_sdk import WeWorkFinanceSDK

# Archive SDK configuration
ARCHIVE_SECRET = os.getenv("ARCHIVE_SECRET", "")
_archive_sdk: WeWorkFinanceSDK | None = None

def _get_archive_sdk() -> Optional[WeWorkFinanceSDK]:
    """Lazy initialization of the Finance SDK."""
    global _archive_sdk
    if _archive_sdk is None:
        if not ARCHIVE_SECRET:
            logger.warning("[ARCHIVE] ARCHIVE_SECRET not set, file retrieval disabled")
            return None
        try:
            sdk = WeWorkFinanceSDK()
            if sdk.init(WECOM_CORP_ID, ARCHIVE_SECRET):
                _archive_sdk = sdk
                logger.info("[ARCHIVE] Finance SDK initialized successfully")
            else:
                logger.error("[ARCHIVE] Finance SDK initialization failed")
        except Exception as e:
            logger.error(f"[ARCHIVE] Error initializing Finance SDK: {e}")
    return _archive_sdk


async def sync_archive_messages():
    """
    Sync new messages from WeCom Archive service.
    
    This function pulls encrypted messages using GetChatData,
    decrypts them using the RSA private key and the Finance SDK,
    and then processes any file messages.
    """
    sdk = _get_archive_sdk()
    if not sdk:
        logger.error("[ARCHIVE_SYNC] SDK not available")
        return

    # 1. Get current sequence from DB
    try:
        conn = get_context_manager().storage._sqlite_conn
        cursor = conn.cursor()
        cursor.execute("SELECT seq FROM archive_cursor WHERE id = 1")
        row = cursor.fetchone()
        current_seq = row[0] if row else 0
    except Exception as e:
        logger.error(f"[ARCHIVE_SYNC] Failed to get cursor: {e}")
        current_seq = 0

    logger.info(f"[ARCHIVE_SYNC] Starting sync from seq={current_seq}")

    # 2. Pull messages in batches
    limit = 100
    has_more = True
    
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import PKCS1_v1_5
    import base64

    # Load private key once
    try:
        with open(ARCHIVE_PRIVATE_KEY_PATH, "rb") as f:
            priv_key = RSA.importKey(f.read())
            rsa_cipher = PKCS1_v1_5.new(priv_key)
    except Exception as e:
        logger.error(f"[ARCHIVE_SYNC] Failed to load private key from {ARCHIVE_PRIVATE_KEY_PATH}: {e}")
        return

    while has_more:
        try:
            # Run SDK call in executor
            import asyncio
            loop = asyncio.get_event_loop()
            chat_data = await loop.run_in_executor(None, lambda: sdk.get_chat_data(current_seq, limit))
            
            if not chat_data:
                logger.info("[ARCHIVE_SYNC] No more messages to pull")
                has_more = False
                break
                
            logger.info(f"[ARCHIVE_SYNC] Pulled {len(chat_data)} encrypted messages")
            
            max_seq = current_seq
            for msg_item in chat_data:
                seq = msg_item.get("seq", 0)
                if seq > max_seq:
                    max_seq = seq
                    
                # Decrypt this message
                encrypt_random_key = msg_item.get("encrypt_random_key")
                encrypt_chat_msg = msg_item.get("encrypt_chat_msg")
                
                if not encrypt_random_key or not encrypt_chat_msg:
                    continue
                    
                # a) RSA decrypt random key
                try:
                    random_key_bytes = rsa_cipher.decrypt(base64.b64decode(encrypt_random_key), None)
                    if not random_key_bytes:
                        logger.error(f"[ARCHIVE_SYNC] RSA decryption failed for seq={seq}")
                        continue
                    
                    random_key = random_key_bytes.decode('utf-8')
                    
                    # b) Finance SDK decrypt message
                    decrypted_json = await loop.run_in_executor(
                        None, lambda: sdk.decrypt_data(random_key, encrypt_chat_msg)
                    )
                    
                    if not decrypted_json:
                        logger.error(f"[ARCHIVE_SYNC] Finance SDK decryption failed for seq={seq}")
                        continue
                        
                    # c) Process message JSON
                    message = json.loads(decrypted_json)
                    await process_archive_message(message)
                    
                except Exception as e:
                    logger.error(f"[ARCHIVE_SYNC] Error processing seq={seq}: {e}")
            
            # 3. Update cursor
            current_seq = max_seq
            cursor.execute("UPDATE archive_cursor SET seq = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1", (current_seq,))
            conn.commit()
            
            # If we got fewer messages than limit, we're likely caught up
            if len(chat_data) < limit:
                has_more = False
                
        except Exception as e:
            logger.error(f"[ARCHIVE_SYNC] Sync batch error: {e}")
            has_more = False

    logger.info(f"[ARCHIVE_SYNC] Sync complete. Current seq={current_seq}")


async def process_archive_message(message: dict):
    """
    Process an archived message.
    
    We're mainly interested in file messages for automatic collection.
    """
    msg_type = message.get("msgtype", "")
    chat_id = message.get("roomid", "")  # Group chat ID
    sender_id = message.get("from", "")
    msg_id = message.get("msgid", "")
    
    logger.info(f"[ARCHIVE_PROCESS] Processing {msg_type} message from {sender_id} in {chat_id}")
    
    # Only process file messages for now
    if msg_type != "file":
        logger.debug(f"[ARCHIVE_PROCESS] Ignoring {msg_type} message")
        return
    
    # Extract file information
    file_info = message.get("file", {})
    filename = file_info.get("filename", "unknown")
    file_size = file_info.get("filesize", 0)
    sdkfileid = file_info.get("sdkfileid", "")
    
    if not sdkfileid:
        logger.error("[ARCHIVE_PROCESS] No sdkfileid in file message")
        return
    
    logger.info(f"[ARCHIVE_PROCESS] File detected: {filename} ({file_size} bytes)")
    
    # 1. Download file using archive SDK
    sdk = _get_archive_sdk()
    if not sdk:
        logger.warning("[ARCHIVE_PROCESS] Archive SDK not available, skipping download")
        return

    try:
        logger.info(f"[ARCHIVE_DOWNLOAD] Starting download for {filename} (id={sdkfileid[:20]}...)")
        # Run synchronous SDK call in executor
        import asyncio
        loop = asyncio.get_running_loop()
        file_content = await loop.run_in_executor(None, lambda: sdk.get_media_data(sdkfileid))
        
        if not file_content:
            logger.error(f"[ARCHIVE_DOWNLOAD] Download failed for {filename}")
            return
            
        logger.info(f"[ARCHIVE_DOWNLOAD] Downloaded {len(file_content)} bytes for {filename}")

        # 2. Upload to Qiniu
        storage = get_storage_manager()
        upload_res = storage.upload_file(file_content, filename)
        file_uri = upload_res.url
        logger.info(f"[ARCHIVE_UPLOAD] Uploaded to Qiniu: {file_uri}")
        
        # 3. Save to database
        context_manager = get_context_manager()
        context_manager.save_file(
            chat_id=chat_id,
            sender_id=sender_id,
            wecom_msg_id=msg_id,
            filename=filename,
            file_uri=file_uri,
            storage_key=upload_res.key
        )
        logger.info(f"[ARCHIVE_DB] File context saved for {filename} in chat {chat_id}")
        
    except Exception as e:
        logger.error(f"[ARCHIVE_PROCESS] Error handling file {filename}: {e}")
    
    logger.info(f"[ARCHIVE_PROCESS] File processing complete: {filename}")
