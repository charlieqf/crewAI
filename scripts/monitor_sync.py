import sqlite3
import datetime

db_path = '/var/lib/wecom-callback/chat_history.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()

TARGET_ROOM = 'wrQakDCgAAFdWnEoo0v4_y6PkzdOp9YQ'

print("--- Sync Progress Report ---")
cur.execute("SELECT seq, updated_at FROM archive_cursor WHERE id = 1")
row = cur.fetchone()
print(f"Current Cursor: {row[0]} (Updated: {row[1]})")

print("\n--- Date Distribution (Jan 13 onwards) ---")
cur.execute("""
    SELECT date(created_at), COUNT(*) 
    FROM archived_messages 
    WHERE created_at >= '2026-01-13'
    GROUP BY date(created_at)
    ORDER BY date(created_at) ASC
""")
for date, count in cur.fetchall():
    print(f"  {date}: {count} messages")

print(f"\n--- Target Room Analysis ({TARGET_ROOM}) ---")
cur.execute("""
    SELECT date(created_at), COUNT(*)
    FROM archived_messages
    WHERE room_id = ? AND created_at >= '2026-01-13'
    GROUP BY date(created_at)
    ORDER BY date(created_at) ASC
""", (TARGET_ROOM,))
rows = cur.fetchall()
if rows:
    for date, count in rows:
        print(f"  {date}: {count} messages")
else:
    print("  No messages found for this room since Jan 13 in current synced range.")

print("\n--- Latest Messages (by Seq) ---")
cur.execute("SELECT seq, created_at FROM archived_messages ORDER BY seq DESC LIMIT 5")
for seq, ts in cur.fetchall():
    print(f"  Seq={seq}, Time={ts}")

conn.close()
