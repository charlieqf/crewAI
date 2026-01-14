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

# Shared SQL fragment to normalize timestamps across ISO/epoch(ms/s)
SQL_TS_NORM = """
CASE 
    WHEN {col} GLOB '[0-9]*' AND {col} NOT GLOB '*:*' THEN 
        CASE 
            WHEN length({col}) >= 13 THEN datetime(CAST({col} AS INTEGER)/1000, 'unixepoch')
            ELSE datetime(CAST({col} AS INTEGER), 'unixepoch')
        END
    ELSE {col} 
END
"""


def _parse_time_range(pattern: str) -> Optional[timedelta]:
    """
    Parse time range patterns like '2d', '3d', '1w'.
    
    Args:
        pattern: String like '2d' (2 days), '1w' (1 week), '3d' (3 days)
        
    Returns:
        timedelta object, or None if pattern doesn't match
    """
    import re
    match = re.match(r"^(\d+)([dwh])$", pattern.lower().strip())
    if not match:
        return None
    
    value = int(match.group(1))
    unit = match.group(2)
    
    if unit == "d":
        return timedelta(days=value)
    elif unit == "w":
        return timedelta(weeks=value)
    elif unit == "h":
        return timedelta(hours=value)
    
    return None

def get_merged_chat_history(
    room_id: str, 
    date: str = "today", 
    limit: int = 500
) -> List[Dict[str, Any]]:
    """
    Retrieves and merges chat history from two sources:
    1. chat_history.db (Audit data)
    2. chat_storage.db (Hot data/Bot responses)
    
    Args:
        date: "today", "yesterday", "last_24h", "2d", "3d", "1w", or "YYYY-MM-DD"
              Supports patterns: Nd (last N days), Nw (last N weeks)
    """
    # Use Beijing time for relative date keywords (server may be in different timezone)
    now_bj = datetime.now(BEIJING_TZ)
    
    # Determine query mode and parameters
    use_range_query = False
    since_ts = None
    
    if date == "last_24h":
        # Range query: last 24 hours from now (Beijing time)
        since_ts = (now_bj - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        target_date = None
        use_range_query = True
        logger.info(f"[ARCHIVE] Using 24h range query, since={since_ts} (Beijing time)")
    elif date == "today":
        target_date = now_bj.strftime("%Y-%m-%d")
    elif date == "yesterday":
        target_date = (now_bj - timedelta(days=1)).strftime("%Y-%m-%d")
    elif _parse_time_range(date):
        # Parse patterns like "2d", "3d", "1w"
        delta = _parse_time_range(date)
        since_ts = (now_bj - delta).strftime("%Y-%m-%d %H:%M:%S")
        target_date = None
        use_range_query = True
        logger.info(f"[ARCHIVE] Using {date} range query, since={since_ts} (Beijing time)")
    else:
        target_date = date

    if use_range_query:
        audit_msgs = _fetch_audit_messages(room_id, since_ts, limit, is_range=True)
        hot_msgs = _fetch_hot_messages(room_id, since_ts, limit, is_range=True)
    else:
        audit_msgs = _fetch_audit_messages(room_id, target_date, limit, is_range=False)
        hot_msgs = _fetch_hot_messages(room_id, target_date, limit, is_range=False)

    # Merge and heal
    merged = _merge_and_heal(audit_msgs, hot_msgs)
    
    # Robust Sort: Convert all timestamps to a comparable ISO format or epoch
    def get_sort_key(m):
        return _normalize_ts_to_iso(m.get("timestamp", ""))

    merged.sort(key=get_sort_key)
    
    return merged[-limit:]

def _normalize_ts_to_iso(ts: Any) -> str:
    """Normalize various timestamp formats to ISO strings for sorting/signatures."""
    # Handle numeric types directly
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()

    ts_str = str(ts).strip()
    if ts_str.isdigit() and len(ts_str) >= 10:
        try:
            val = float(ts_str)
            if val > 1e11:
                val /= 1000  # Convert ms to s
            return datetime.fromtimestamp(val, tz=timezone.utc).isoformat()
        except Exception:
            return ts_str
    return ts_str


def _fetch_audit_messages(room_id: str, ts_filter: str, limit: int, is_range: bool) -> List[Dict[str, Any]]:
    """Fetch audit messages by date or range from chat_history.db."""
    msgs: List[Dict[str, Any]] = []
    if not os.path.exists(ARCHIVE_DB_PATH):
        logger.warning(f"Archive DB not found: {ARCHIVE_DB_PATH}")
        return msgs

    ts_expr = SQL_TS_NORM.format(col="created_at")
    if is_range:
        # For range queries, compare the full timestamp expression
        filter_expr = ts_expr
        comparator = ">="
    else:
        # For date queries, extract only the date part
        filter_expr = f"strftime('%Y-%m-%d', {ts_expr})"
        comparator = "="

    query = f"""
        SELECT seq, msgid, sender_id, content, created_at 
        FROM archived_messages 
        WHERE room_id = ? AND 
        {filter_expr} {comparator} ?
        ORDER BY seq DESC
        LIMIT ?
    """

    try:
        with sqlite3.connect(ARCHIVE_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (room_id, ts_filter, limit))
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
    except Exception as e:
        logger.error(f"Error fetching audit messages: {e}")

    return msgs[::-1]  # Reverse to restore chronological order


def _fetch_hot_messages(chat_id: str, ts_filter: str, limit: int, is_range: bool) -> List[Dict[str, Any]]:
    """Fetch bot responses and @mentions by date or range from chat_storage.db."""
    msgs: List[Dict[str, Any]] = []
    if not os.path.exists(HOT_DB_PATH):
        logger.warning(f"Hot DB not found: {HOT_DB_PATH}")
        return msgs

    try:
        with sqlite3.connect(HOT_DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(chat_messages)")
            columns = [col[1] for col in cursor.fetchall()]

            select_cols = ["sender_name", "content", "timestamp", "role", "wecom_msg_id"]
            if "bot_type" in columns:
                select_cols.append("bot_type")

            col_string = ", ".join(select_cols)
            ts_expr = SQL_TS_NORM.format(col="timestamp")
            
            if is_range:
                filter_expr = ts_expr
                comparator = ">="
            else:
                filter_expr = f"strftime('%Y-%m-%d', {ts_expr})"
                comparator = "="

            query = f"""
                SELECT {col_string}
                FROM chat_messages
                WHERE chat_id = ? AND 
                {filter_expr} {comparator} ?
                ORDER BY id DESC
                LIMIT ?
            """

            cursor.execute(query, (chat_id, ts_filter, limit))
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
    except Exception as e:
        logger.error(f"Error fetching hot messages: {e}")

    return msgs[::-1]  # Reverse to restore chronological order

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
            ts_sig = _normalize_ts_to_iso(msg['timestamp'])
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
                ts_sig = _normalize_ts_to_iso(amsg['timestamp'])
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
