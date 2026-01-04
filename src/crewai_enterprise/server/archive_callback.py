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

router = APIRouter()


def verify_signature(signature: str, timestamp: str, nonce: str, echo_str: str) -> bool:
    """
    Verify URL signature from WeCom.
    
    Algorithm: sha1(sort(token, timestamp, nonce, echostr))
    """
    if not ARCHIVE_TOKEN:
        logger.error("[ARCHIVE] ARCHIVE_TOKEN not configured")
        return False
    
    params = sorted([ARCHIVE_TOKEN, timestamp, nonce, echo_str])
    concatenated = "".join(params)
    calculated = hashlib.sha1(concatenated.encode()).hexdigest()
    
    return calculated == signature


def decrypt_aes(encrypted_msg: str) -> Optional[dict]:
    """
    Decrypt AES encrypted message from WeCom.
    
    Args:
        encrypted_msg: Base64 encoded encrypted message
    
    Returns:
        Decrypted message as dict, or None if decryption fails
    """
    # TODO: Implement AES decryption
    # This will be implemented after we have the actual AES key from WeCom
    logger.warning("[ARCHIVE] AES decryption not yet implemented")
    return None


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
    
    # Verify signature
    if not verify_signature(msg_signature, timestamp, nonce, echostr):
        logger.error("[ARCHIVE_VERIFY] Signature verification failed")
        raise HTTPException(status_code=403, detail="Signature verification failed")
    
    logger.info("[ARCHIVE_VERIFY] Signature verified successfully")
    
    # TODO: Decrypt echostr (AES encrypted)
    # For now, return the echostr as-is (this might not work)
    # We need to implement proper AES decryption
    
    return Response(content=echostr, media_type="text/plain")


@router.post("/wecom/archive-callback")
async def archive_callback_message(request: Request):
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
    logger.info("[ARCHIVE_MSG] Received message callback")
    
    # Get query parameters
    params = request.query_params
    msg_signature = params.get("msg_signature", "")
    timestamp = params.get("timestamp", "")
    nonce = params.get("nonce", "")
    
    # Get request body
    body = await request.body()
    
    # Parse encrypted message
    try:
        data = json.loads(body)
        encrypted_msg = data.get("encrypt", "")
    except json.JSONDecodeError:
        logger.error("[ARCHIVE_MSG] Invalid JSON in request body")
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    # Verify signature
    if not verify_signature(msg_signature, timestamp, nonce, encrypted_msg):
        logger.error("[ARCHIVE_MSG] Signature verification failed")
        raise HTTPException(status_code=403, detail="Signature verification failed")
    
    # Decrypt message
    message = decrypt_aes(encrypted_msg)
    if not message:
        logger.error("[ARCHIVE_MSG] Message decryption failed")
        # Don't return error, just log and continue
        # WeCom expects 200 OK even if we can't process the message
        return {"status": "ok"}
    
    # Process message
    try:
        await process_archive_message(message)
    except Exception as e:
        logger.error(f"[ARCHIVE_MSG] Error processing message: {e}")
        # Still return success to WeCom
    
    return {"status": "ok"}


async def process_archive_message(message: dict):
    """
    Process an archived message.
    
    We're mainly interested in file messages for automatic collection.
    
    Message types:
    - text: Ignore
    - image: Could collect for image analysis
    - file: IMPORTANT - collect PDF, Office docs, etc.
    - voice: Ignore
    - video: Maybe collect later
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
    
    #TODO: Download file using archive SDK
    # file_content = download_archive_file(sdkfileid)
    
    # TODO: Upload to Qiniu
    # storage = get_storage_manager()
    # file_uri = await storage.upload_file(file_content, filename)
    
    # TODO: Save to database
    # context_manager = get_context_manager()
    # context_manager.save_file(
    #     chat_id=chat_id,
    #     sender_id=sender_id,
    #     wecom_msg_id=msg_id,
    #     filename=filename,
    #     file_uri=file_uri,
    #     upload_time=int(time.time())
    # )
    
    logger.info(f"[ARCHIVE_PROCESS] File processing complete: {filename}")
