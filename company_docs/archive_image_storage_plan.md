# Archive Image Storage Implementation Plan (v2)

## Team Findings Addressed

| Finding | Severity | Resolution |
|---------|----------|------------|
| sender_id extraction | 🔴 High | **Verified: `from` is a string, same as `process_file_message`** |
| Filename assumes JPEG | 🟡 Medium | Use `msgid` as base, infer extension from magic bytes |
| Placeholder non-ASCII | 🟡 Medium | Use ASCII placeholder `[Image]` |
| room_id for 1:1 | 🟢 Low | Match `process_file_message` logic (empty string if absent) |

## Verified Current Behavior

```python
# process_file_message uses:
msg.get("roomid", "")   # ← room_id, empty for 1:1
msg.get("from", "")     # ← sender_id (string, NOT nested)
```

The decrypted WeCom archive message structure:
```json
{
    "msgtype": "image",
    "msgid": "xxx",
    "from": "zhangsan",           // ← String, not nested!
    "roomid": "wrksxxx",          // ← Only for group chats
    "image": {
        "sdkfileid": "xxx",
        "md5sum": "xxx",
        "filesize": 123456
    }
}
```

## Updated Implementation

### `process_image_message()` Function

```python
def process_image_message(sdk, msg: dict, cursor) -> bool:
    """Download image from WeCom and upload to Qiniu."""
    try:
        image_info = msg.get("image", {})
        sdkfileid = image_info.get("sdkfileid")
        file_size = image_info.get("filesize", 0)
        msgid = msg.get("msgid", "")
        
        if not sdkfileid:
            logger.warning(f"No sdkfileid in image message {msgid}")
            return False
        
        if file_size and file_size > MAX_ARCHIVE_FILE_BYTES:
            logger.warning(f"Skipping large image ({file_size} bytes)")
            return False
        
        # Download image using SDK
        file_bytes = sdk.get_media_data(sdkfileid)
        if not file_bytes:
            logger.error(f"Failed to download image {sdkfileid}")
            return False
        
        # Detect image type from magic bytes
        extension = _detect_image_extension(file_bytes)
        
        # Use msgid as filename base (unique and available)
        filename = f"image_{msgid[:16]}{extension}"
        
        # Upload to Qiniu with correct content-type
        content_type = _get_content_type(extension)
        file_uri = upload_to_qiniu(file_bytes, filename, content_type)
        if not file_uri:
            return False
        
        # Save to database (match process_file_message exactly)
        cursor.execute("""
            INSERT OR REPLACE INTO chat_files 
            (msgid, room_id, sender_id, filename, file_size, file_uri, created_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            msgid,
            msg.get("roomid", ""),   # Empty for 1:1 chats
            msg.get("from", ""),     # String user_id
            filename,
            len(file_bytes),
            file_uri
        ))
        
        logger.info(f"Saved image: {filename} -> {file_uri}")
        return True
        
    except Exception as e:
        logger.error(f"Error processing image: {e}")
        return False


def _detect_image_extension(file_bytes: bytes) -> str:
    """Detect image type from magic bytes."""
    if file_bytes[:3] == b'\xff\xd8\xff':
        return ".jpg"
    elif file_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        return ".png"
    elif file_bytes[:6] in (b'GIF87a', b'GIF89a'):
        return ".gif"
    elif file_bytes[:4] == b'RIFF' and file_bytes[8:12] == b'WEBP':
        return ".webp"
    else:
        return ".jpg"  # Default fallback


def _get_content_type(extension: str) -> str:
    """Get MIME type for image extension."""
    return {
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(extension, "image/jpeg")
```

### Update `sync()` to Handle Images

```diff
# Handle file messages
if msg_type == "file":
    if process_file_message(sdk, decrypted_msg, cursor):
        files_processed += 1

+# Handle image messages
+if msg_type == "image":
+    if process_image_message(sdk, decrypted_msg, cursor):
+        files_processed += 1
```

### Archive Webpage Image Display

```python
# When building message HTML (use ASCII placeholder)
if msg_type == "image":
    file_uri = get_image_uri_for_message(msgid)
    if file_uri:
        return f'<img src="{file_uri}" style="max-width:300px" alt="Image">'
    else:
        return "[Image]"  # ASCII placeholder
```

## Files to Modify

| File | Change |
|------|--------|
| `scripts/archive_sync_worker.py` | Add `process_image_message()`, `_detect_image_extension()`, update `sync()` |
| `src/crewai_enterprise/server/archive_callback.py` | Update message rendering with ASCII placeholder |

## Verification Plan

1. Deploy updated `archive_sync_worker.py`
2. Send test images (JPEG, PNG, GIF) in archived group
3. Trigger archive sync
4. Verify:
   - Correct file extension detected
   - Qiniu URL stored in `chat_files`
   - Image displays on archive webpage
