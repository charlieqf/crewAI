import os
import sys
from datetime import datetime, timedelta, timezone

# Add project root to path
sys.path.append(os.path.abspath("."))

from src.crewai_enterprise.tools.archive.archive_tool import get_merged_chat_history, BEIJING_TZ

def test_archive_tool():
    room_id = "wrQakDCgAAa-wxaHCLgJ929glNlcKfBg" # Test room found earlier
    print(f"Testing Archive Tool for room: {room_id}")
    
    # 1. Test Date-based Query (today)
    print("\n--- Testing 'today' ---")
    today_msgs = get_merged_chat_history(room_id, date="today", limit=5)
    print(f"Found {len(today_msgs)} messages for today.")
    for m in today_msgs:
        print(f"[{m['timestamp']}] {m['sender']}: {m['content'][:50]}...")

    # 2. Test Range-based Query (last_24h)
    print("\n--- Testing 'last_24h' ---")
    range_msgs = get_merged_chat_history(room_id, date="last_24h", limit=5)
    print(f"Found {len(range_msgs)} messages for last 24h.")
    # Verify granularity: if we have any messages, check if they have times
    for m in range_msgs:
        print(f"[{m['timestamp']}] {m['sender']}: {m['content'][:50]}...")

    # 3. Test Sorting 
    if range_msgs:
        print("\n--- Verifying Sorting ---")
        timestamps = [m['timestamp'] for m in range_msgs]
        sorted_timestamps = sorted(timestamps)
        if timestamps == sorted_timestamps:
            print("✅ Timestamps are correctly sorted.")
        else:
            print("❌ Timestamps are NOT sorted correctly.")
            print(f"Original: {timestamps}")
            print(f"Sorted:   {sorted_timestamps}")

if __name__ == "__main__":
    test_archive_tool()
