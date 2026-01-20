# Scenario 04: Iterative File Refinement

## Scenario Description

After generating a file, the user wants to refine it based on previous results, such as "redo a version" or "change to a fintech style".

## Core Requirements

1. **Support Iterative Refinement**: Users can modify based on previous files.
2. **Retain Full Context**: AI knows what was generated before.
3. **File Expiration**: Auto-sticky context expires after 10 minutes.
4. **Quote Support**: Users can quote specific files for precision.

## Conversation Examples

### Iterative Refinement Flow
```
User: @gemini /file-html Make a login page
Gemini: Cloud Link: http://wecomfile.medmeeting.com/wecom/v1.html

User: @gemini /file-html Redo a version, change style to fintech
Gemini: Cloud Link: http://wecomfile.medmeeting.com/wecom/v2.html
# AI changes style to fintech based on the previous login page

User: @gemini /file-html Change it again, use gradient buttons
Gemini: Cloud Link: http://wecomfile.medmeeting.com/wecom/v3.html
# AI changes buttons to gradient based on the fintech style
```

### Quote-Based Refinement
```
User: @gemini /file-html Login page
Gemini: Cloud Link: http://.../login.html

User: @gemini /file-html Registration page
Gemini: Cloud Link: http://.../register.html

User: [Quotes the login.html message]
User: @gemini /file-html Improve this page, add dark mode
Gemini: Cloud Link: http://.../login_v2.html
# AI precisely identifies which file to improve via quoted message
```

## File Context Retrieval

### Priority Order
The system retrieves file context in this order:

1. **Quoted Message ID** - Highest priority, user explicitly quotes a file
2. **Quoted Filename** - User mentions a specific filename
3. **Latest File (Sticky)** - Most recent file within 10-minute window

### Code Implementation
```python
# 1. Quoted File (Specific) - by MsgId
file_ctx = None
if quoted_msg_id:
    file_ctx = context_manager.get_active_file(chat_id, wecom_msg_id=quoted_msg_id, bot_type=bot_type)

# 2. Quoted File (Specific) - by Filename
if not file_ctx and quoted_filename:
    file_ctx = context_manager.get_active_file(chat_id, filename=quoted_filename, bot_type=bot_type)

# 3. Latest File (Sticky) - with 10-minute time window
if not file_ctx:
    file_ctx = context_manager.get_active_file(chat_id, limit=50, bot_type=bot_type)
    
    # Check if file is within 10-minute window
    if file_ctx:
        file_timestamp = file_ctx.get("timestamp", 0)
        elapsed_minutes = (time.time() - file_timestamp) / 60
        
        if elapsed_minutes > 10:
            logger.info(f"File expired (age: {elapsed_minutes:.1f}min > 10min)")
            file_ctx = None  # Expired, don't use
```

## File Storage Format

### Saving File Context
```python
# When generating a file
context_manager.save_file(
    chat_id=chat_id,
    sender_id=f"bot_{bot_type}",
    sender_name=bot_type,
    file_uri=cloud_url,       # Cloud link
    filename=filename,         # output.html
    mime_type="text/html",
    wecom_msg_id=wecom_msg_id,
    bot_type=bot_type,
    storage_key=storage_key,   # Links file to message
)
```

### File Context Data Structure
```python
file_ctx = {
    "uri": "http://wecomfile.medmeeting.com/wecom/xxx.html",
    "filename": "output.html",
    "mime": "text/html",
    "timestamp": 1705551234.567,
    "storage_key": "abc123"  # Links to original message
}
```

## 10-Minute Sticky Window

| Scenario | Behavior |
|----------|----------|
| User sends `/file-html` within 10 min of last file | Previous file context is available |
| User sends `/file-html` after 10+ min | No automatic file context (starts fresh) |
| User quotes a specific file | Quoted file used regardless of age |

> [!NOTE]
> The 10-minute window only applies to **automatic (sticky) context**. Explicitly quoted files are always retrieved regardless of age.

## Message Flow Diagram

```
User: "@gemini /file-html Improve the design"
           │
           ▼
┌─────────────────────────┐
│ Check for Quoted Msg ID │
│ → If found, use it      │
└───────────┬─────────────┘
           │ (not found)
           ▼
┌─────────────────────────┐
│ Check for Quoted Filename│
│ → If found, use it       │
└───────────┬─────────────┘
           │ (not found)
           ▼
┌─────────────────────────┐
│ Get Latest File (Sticky)│
│ → Check 10-min window   │
└───────────┬─────────────┘
           │
           ▼
┌─────────────────────────┐
│ If valid file_ctx:      │
│ Inject file into prompt │
└───────────┬─────────────┘
           │
           ▼
        Call LLM
```

## Expected Behavior Table

| User Action | System Behavior |
|-------------|-----------------|
| `/file-html improve it` (within 10min) | Uses last generated file as context |
| `/file-html improve it` (after 10min) | Starts fresh, no file context |
| Quote + `/file-html improve this` | Uses quoted file regardless of age |
| Mention filename "improve login.html" | Searches for file by name |

## Design Decisions

| Decision Point | Current Solution | Rationale |
|----------------|------------------|-----------|
| Sticky window duration | 10 minutes | Balance between convenience and context pollution |
| File content in context | Link + metadata only | Full HTML would consume too many tokens |
| Quote priority | Highest | User intent is explicit |

## Related Features

- **storage_key**: Links generated files back to original messages
- **bot_type isolation**: Each bot maintains separate file context
- **Filename matching**: Supports substring matching for flexibility
