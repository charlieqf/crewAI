import sqlite3
import os

HISTORY_DB = "/var/lib/wecom-callback/chat_history.db"
STORAGE_DB = "/var/lib/wecom-callback/chat_storage.db"

def recover_storage_keys():
    # Connect to storage DB
    conn = sqlite3.connect(STORAGE_DB)
    cursor = conn.cursor()
    
    # Attach history DB
    cursor.execute(f"ATTACH DATABASE '{HISTORY_DB}' AS history_db")
    
    # Update storage_key from chat_files
    # Join on msgid
    cursor.execute("""
        UPDATE file_contents
        SET storage_key = (
            SELECT file_uri 
            FROM history_db.chat_files 
            WHERE history_db.chat_files.msgid = file_contents.wecom_msg_id
            LIMIT 1
        )
        WHERE storage_key IS NULL
    """)
    
    affected = conn.total_changes
    conn.commit()
    conn.close()
    print(f"Recovered {affected} storage keys.")

if __name__ == "__main__":
    recover_storage_keys()
