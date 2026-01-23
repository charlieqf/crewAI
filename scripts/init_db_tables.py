import sqlite3

conn = sqlite3.connect('chat_storage.db')
cursor = conn.cursor()

# Archive cursor table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS archive_cursor (
        id INTEGER PRIMARY KEY,
        seq INTEGER,
        updated_at TEXT
    )
''')
cursor.execute('INSERT OR IGNORE INTO archive_cursor (id, seq) VALUES (1, 0)')

# Archived messages table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS archived_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        seq INTEGER,
        msgid TEXT UNIQUE,
        msgtype TEXT,
        sender_id TEXT,
        room_id TEXT,
        content TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

# Chat files table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS chat_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        msgid TEXT,
        room_id TEXT,
        sender_id TEXT,
        filename TEXT,
        file_size INTEGER,
        file_uri TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
''')

# File contents table (for OCR extraction)
cursor.execute('''
    CREATE TABLE IF NOT EXISTS file_contents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT,
        wecom_msg_id TEXT,
        storage_key TEXT,
        file_hash TEXT NOT NULL,
        filename TEXT,
        mime_type TEXT,
        size_bytes INTEGER,
        page_count INTEGER,
        extracted_text TEXT,
        extracted_summary TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        error_message TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        extracted_at TEXT
    )
''')

# Create indexes
cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_file_hash ON file_contents(file_hash)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_chat_msg ON file_contents(chat_id, wecom_msg_id)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_storage ON file_contents(storage_key)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_status ON file_contents(status)')

conn.commit()
conn.close()
print('All tables created successfully')
