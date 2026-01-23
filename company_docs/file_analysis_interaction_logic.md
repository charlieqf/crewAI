# File Analysis Interaction Logic: Private vs Group Chats

This document explains how the AI bot handles file analysis within the constraints of the WeCom (Work WeChat) platform, specifically addressing why different mechanisms are used for private and group chats.

## The WeCom Constraint
In WeCom **Group Chats**, a message of type `file` cannot contain text or an `@mention`. Consequently, the bot server (Webhook) does not receive a callback when a file is sent in a group unless explicitly mentioned—which is impossible for standard file uploads.

## Interaction Scenarios

### 1. Private Chat (One-on-One)
In private chats, `@mention` is not required.
- **Trigger**: User sends a file (PDF, Doc, Image).
- **Mechanism**: `aibot_callback.py` receives a `msgtype="file"` callback immediately.
- **User Experience**: The bot responds instantly with *"正在分析文件..." (Analyzing file...)* and starts the extraction.
- **Flow**: Hot Flow (Direct Callback).

### 2. Group Chat (The Seamless Workaround)
Since the bot cannot be @mentioned on a file upload, we rely on a "Synchronize-then-Retrieve" strategy.

#### Phase A: Background Sync (Cold Flow)
- **Trigger**: Any user sends a file to the group.
- **Mechanism**: The **`archive_sync_worker.py`** (running via WeCom Archive SDK) pulls the message in the background.
- **Action**: It downloads the file, uploads it to cloud storage, performs OCR/extraction, and caches the text in the `file_contents` table.
- **Result**: The bot remains silent, but its "memory" is updated.

#### Phase B: Contextual Query (Hot Flow)
- **Trigger**: User sends `@Bot 总结一下刚才的文件` (Summarize the file just sent) or **Quotes/Replies** to the file message and `@Bot`.
- **Mechanism**: `aibot_callback.py` receives a `msgtype="text"` callback.
- **Action**: The `llm_orchestrator.py` looks for context in the following priority:
    1. **Quoted File**: If the user explicitly replied to a file, find its content by `msg_id`.
    2. **Sticky Window**: If no quote, look for the most recent file in that group from the last **10 minutes**.
- **User Experience**: Even though the bot didn't "see" the file upload event, it "remembers" the content via the database and answers accurately.

---

## Technical Synergy Table

| Feature | Private Chat | Group Chat |
| :--- | :--- | :--- |
| **Immediate Callback** | Yes (`msgtype="file"`) | No |
| **Response Trigger** | File Upload | Text Message (@mention/Quote) |
| **Extraction Origin** | Hot Flow (Callback Server) | Cold Flow (Archive Sync Worker) |
| **Data Source** | In-memory + Cache | Cached `file_contents` Table |
| **Multi-modal Support** | Native (if supported) | Extracted Text Injection |

## Summary
The combination of **Hot Flow** (for instant private chat response) and **Cold Flow** (for background group chat synchronization) ensures that the bot provides a consistent and reliable file analysis experience regardless of platform-specific interaction limits.
