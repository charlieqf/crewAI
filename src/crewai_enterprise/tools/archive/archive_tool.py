"""
Archive Retrieval Tool - Merges Audit and Bot messages for a unified chat history.
"""

import os
import sqlite3
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# UTC+8 Timezone for Beijing/WeCom
BEIJING_TZ = timezone(timedelta(hours=8))

# Database paths
ARCHIVE_DB_PATH = os.getenv("ARCHIVE_DB_PATH", "/var/lib/wecom-callback/chat_history.db")
HOT_DB_PATH = os.getenv("CHAT_DB_PATH", "/var/lib/wecom-callback/chat_storage.db")

def get_merged_chat_history(
    room_id: str, 
    date: str = "today", 
    limit: int = 500
) -> List[Dict[str, Any]]:
    """
    Retrieves and merges chat history from two sources:
    1. chat_history.db (Audit data)
    2. chat_storage.db (Hot data/Bot responses)
    """
    # Use Beijing time for relative date keywords
    now_bj = datetime.now(BEIJING_TZ)
    
    if date == "today":
        target_date = now_bj.strftime("%Y-%m-%d")
    elif date == "yesterday":
        target_date = (now_bj - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        target_date = date

    audit_msgs = _get_audit_messages(room_id, target_date, limit)
    hot_msgs = _get_hot_messages(room_id, target_date, limit)

    # Merge and heal
    merged = _merge_and_heal(audit_msgs, hot_msgs)
    
    # Robust Sort: Convert all timestamps to a comparable ISO format or epoch
    def get_sort_key(m):
        ts = m.get("timestamp", "")
        # Handle numeric types directly
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        
        # Handle digit-only strings as epochs
        ts_str = str(ts).strip()
        if ts_str.isdigit() and len(ts_str) >= 10:
            try:
                # Handle ms vs s automatically
                val = float(ts_str)
                if val > 1e11: val /= 1000 # Convert ms to s
                return datetime.fromtimestamp(val, tz=timezone.utc).isoformat()
            except: pass
            
        return ts_str

    merged.sort(key=get_sort_key)
    
    return merged[-limit:]

def _get_audit_messages(room_id: str, date_str: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch pure audit messages from chat_history.db."""
    msgs = []
    if not os.path.exists(ARCHIVE_DB_PATH):
        logger.warning(f"Archive DB not found: {ARCHIVE_DB_PATH}")
        return msgs

    try:
        conn = sqlite3.connect(ARCHIVE_DB_PATH)
        cursor = conn.cursor()
        
        # Note: We query by room_id and date. 
        # Content is stored as JSON string in 'content' column.
        # Query the LATEST messages of the day
        # Robustly handle both ISO strings and numeric epochs (seconds or milliseconds)
        query = """
            SELECT seq, msgid, sender_id, content, created_at 
            FROM archived_messages 
            WHERE room_id = ? AND 
            strftime('%Y-%m-%d', 
                CASE 
                    WHEN created_at GLOB '[0-9]*' AND created_at NOT GLOB '*:*' THEN 
                        CASE 
                            WHEN length(created_at) >= 13 THEN datetime(CAST(created_at AS INTEGER)/1000, 'unixepoch')
                            ELSE datetime(CAST(created_at AS INTEGER), 'unixepoch')
                        END
                    ELSE created_at 
                END
            ) = ?
            ORDER BY seq DESC
            LIMIT ?
        """
        cursor.execute(query, (room_id, date_str, limit))
        
        for row in cursor.fetchall():
            seq, msgid, sender_id, raw_content, created_at = row
            try:
                content_dict = json.loads(raw_content)
                text_content = ""
                if content_dict.get("msgtype") == "text":
                    text_content = content_dict.get("text", {}).get("content", "")
                elif content_dict.get("msgtype") == "file":
                    text_content = f"[File: {content_dict.get('file', {}).get('filename', 'unnamed')}]"
                
                msgs.append({
                    "source": "audit",
                    "seq": seq,
                    "msgid": msgid,
                    "sender": sender_id,
                    "content": text_content,
                    "timestamp": created_at,
                    "role": "user"
                })
            except Exception as e:
                logger.error(f"Failed to parse audit message {msgid}: {e}")
                
        conn.close()
    except Exception as e:
        logger.error(f"Error fetching audit messages: {e}")
        
    return msgs[::-1] # Reverse to restore chronological order

def _get_hot_messages(chat_id: str, date_str: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch bot responses and @mentions from chat_storage.db (Latest first)."""
    msgs = []
    if not os.path.exists(HOT_DB_PATH):
        logger.warning(f"Hot DB not found: {HOT_DB_PATH}")
        return msgs

    try:
        conn = sqlite3.connect(HOT_DB_PATH)
        cursor = conn.cursor()
        
        # Check available columns to be resilient to schema variations
        cursor.execute("PRAGMA table_info(chat_messages)")
        columns = [col[1] for col in cursor.fetchall()]
        
        select_cols = ["sender_name", "content", "timestamp", "role", "wecom_msg_id"]
        if "bot_type" in columns:
            select_cols.append("bot_type")
        
        col_string = ", ".join(select_cols)
        # Query the LATEST messages of the day using CASE for epoch/ISO robustness
        query = f"""
            SELECT {col_string}
            FROM chat_messages
            WHERE chat_id = ? AND 
            strftime('%Y-%m-%d', 
                CASE 
                    WHEN timestamp GLOB '[0-9]*' AND timestamp NOT GLOB '*:*' THEN 
                        CASE 
                            WHEN length(timestamp) >= 13 THEN datetime(CAST(timestamp AS INTEGER)/1000, 'unixepoch')
                            ELSE datetime(CAST(timestamp AS INTEGER), 'unixepoch')
                        END
                    ELSE timestamp 
                END
            ) = ?
            ORDER BY id DESC
            LIMIT ?
        """
        cursor.execute(query, (chat_id, date_str, limit))
        
        for row in cursor.fetchall():
            msg_data = dict(zip(select_cols, row))
            msgs.append({
                "source": "hot",
                "sender": msg_data["sender_name"],
                "content": msg_data["content"],
                "timestamp": str(msg_data["timestamp"]),
                "role": msg_data["role"],
                "bot_type": msg_data.get("bot_type"),
                "wecom_msg_id": msg_data["wecom_msg_id"]
            })
            
        conn.close()
    except Exception as e:
        logger.error(f"Error fetching hot messages: {e}")
        
    return msgs[::-1] # Reverse to restore chronological order

def _merge_and_heal(audit_msgs: List[Dict[str, Any]], hot_msgs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merges both lists and 'heals' mangled @mentions in audit messages using hot data.
    """
    merged = []
    
    # 1. Map wecom_msg_id from hot messages for quick lookup
    hot_lookup = {}
    content_lookup = {} # Fallback: stripped content match
    
    for msg in hot_msgs:
        if msg.get("wecom_msg_id"):
            hot_lookup[msg["wecom_msg_id"]] = msg
        
        # Robust lookup: strip "@ ... " prefix and spaces for fuzzy matching
        clean_text = msg["content"].strip()
        if "@" in clean_text:
            clean_text = clean_text.split(None, 1)[-1].strip() if " " in clean_text else clean_text
        
        if clean_text:
            # Normalize timestamp for signature (works for ISO or epoch)
            ts_sig = str(msg['timestamp']).strip()
            if ts_sig.isdigit() and len(ts_sig) >= 10:
                val = float(ts_sig)
                if val > 1e11: val /= 1000
                ts_sig = datetime.fromtimestamp(val, tz=timezone.utc).isoformat()
            
            sig = f"{ts_sig[:16]}_{clean_text}" # Match within the same minute
            content_lookup[sig] = msg

    # 2. Add and heal audit messages
    for amsg in audit_msgs:
        # Healing logic: if content starts with "@ " or seems mangled
        if amsg["content"].startswith("@ "):
            match = hot_lookup.get(amsg["msgid"])
            if not match:
                # Try content matching
                clean_audit = amsg["content"][2:].strip()
                ts_sig = str(amsg['timestamp']).strip()
                if ts_sig.isdigit() and len(ts_sig) >= 10:
                    val = float(ts_sig)
                    if val > 1e11: val /= 1000
                    ts_sig = datetime.fromtimestamp(val, tz=timezone.utc).isoformat()
                
                sig = f"{ts_sig[:16]}_{clean_audit}"
                match = content_lookup.get(sig)
            
            if match:
                amsg["content"] = match["content"]
                amsg["sender"] = match["sender"]
        
        merged.append(amsg)

    # 3. Add bot messages (role == 'assistant') which are exclusively in hot storage
    for hmsg in hot_msgs:
        if hmsg["role"] == "assistant":
            merged.append({
                "source": "hot",
                "sender": hmsg["sender"],
                "content": hmsg["content"],
                "timestamp": hmsg["timestamp"],
                "role": "assistant"
            })

    return merged

if __name__ == "__main__":
    # Test stub
    logging.basicConfig(level=logging.INFO)
    room = "wrQakDCgAAPARKEiyS8Cg3fLSciZUwWw"
    history = get_merged_chat_history(room, date="2026-01-07")
    for m in history:
        print(f"[{m['timestamp']}] {m['sender']}: {m['content']}")
