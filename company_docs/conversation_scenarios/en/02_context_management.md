# Scenario 02: Context Management and Limits

## Scenario Description

Discusses how context is managed in long conversations, when it is truncated, and how users can manually control it.

## Context Limit Mechanism

### Sliding Window Parameters
```python
max_messages = 20   # Maximum number of messages
max_chars = 8000    # Maximum number of characters
```

### Truncation Strategy
1. Prioritize keeping the most recent messages.
2. Remove starting from the earliest messages.
3. System Prompt is always retained.

## Memory Model: Two Independent Storage Systems

> [!IMPORTANT]
> The AI Bot system uses **two completely separate databases** for different purposes.

| System | Database | Purpose | Access Method |
| :--- | :--- | :--- | :--- |
| **LLM Context** | `chat_storage.db` | Store conversation history for AI bots | `ChatContextManager` / `ChatStorageTool` |
| **WeCom Archive** | `chat_history.db` | Compliance archiving of all WeCom messages | `ArchiveSearchTool` / `archive_sync_worker.py` |

### Key Differences

| Aspect | LLM Context (chat_storage.db) | WeCom Archive (chat_history.db) |
| :--- | :--- | :--- |
| **Data Source** | AI bot conversations only | ALL WeCom messages (including non-bot) |
| **Retention** | Rolling window (20 msgs / 8000 chars) | Permanent (years) |
| **Isolation** | Per bot_type | Global (all users, all chats) |
| **Location** | Application directory | `/var/lib/wecom-callback/` |

### Decision Rule: When to Use Archive vs. Context

> [!IMPORTANT]
> **Archive is now automatically injected (default 3h)** for all normal conversations. Users can override with `/Nd` commands.

| User Input | Archive Range | Source |
|------------|---------------|--------|
| Normal conversation | **3h** (auto) | Archive + Hot Context |
| `/1d Question` | 1 day | Archive + Hot Context |
| `/1w Summary` | 1 week | Archive + Hot Context |
| `/file-html 1w Report` | 1 week | Archive + Hot Context |

**Legacy Scenarios (still valid):**
- "What did we say just now?" → **Hot Context** (20-turn window)
- "Keep going" → **Context** (relies on previous turn)

---

## Context Control Commands

### Context Reset (`/reset`, `/new`)

| Command | Effect | Chat History | File Context | Codebase Context |
| :--- | :--- | :--- | :--- | :--- |
| `/reset` | Sets context start timestamp | Messages before timestamp ignored | ❌ Unchanged | ❌ Unchanged |
| `/new` | Logical Break | ❌ Unchanged | ✅ Clears | ❌ Unchanged |

> [!NOTE]
> `/reset` does **not delete data** — it sets a "context start" timestamp. Messages before that timestamp are excluded from the sliding window but remain in the database. Codebase context persists across `/new` as an "environment setting."

> [!IMPORTANT]
> **`/reset` and Archive Injection:**
> - **Default 3h injection** respects `/reset` timestamp (only injects messages after reset)
> - **Explicit `/Nd` commands** bypass `/reset` (user explicitly wants historical data)

### Custom System Prompts (`/set_prompt`, `/show_prompt`, `/reset_prompt`)

Users can set per-bot custom system prompts that persist across conversations:

```python
# Set custom prompt for a specific bot in a chat
context_manager.set_custom_prompt(
    chat_id="group123",
    user_id="user456",
    bot_type="gemini",
    custom_prompt="You are a Python expert. Always provide code examples."
)

# Retrieve custom prompt
prompt = context_manager.get_custom_prompt(chat_id="group123", bot_type="gemini")
```

| Feature | Behavior |
|---------|----------|
| Scope | Per chat + per bot |
| Persistence | Stored in `custom_prompts` table |
| Priority | Custom prompt overrides default system prompt |

---

## Multi-Bot Context Isolation

### Current Implementation (Updated)
- **Policy**: Each bot (gemini/chatgpt/grok) maintains **isolated context** within the same chat.
- **Implementation**: `bot_type` parameter filters messages in `get_context()`.
- **User Intent**: If you talk to `@gemini` and then `@chatgpt`, ChatGPT will NOT see Gemini's responses.

```python
def get_context(self, chat_id: str, bot_type: str | None = None) -> ChatContext:
    # Get messages filtered by bot_type
    result = self.storage._run(
        action="get_recent_json",
        chat_id=chat_id,
        bot_type=bot_type,  # Filters to this bot's messages only
        since_ts=context_start,
        limit=self.max_messages * 2,
    )
    # Apply sliding window limits...
```

### Context Start Timestamp

Each bot can have an independent "context start" timestamp, allowing selective resets:

```python
# Reset context for only gemini in this chat
context_manager.set_context_start(
    chat_id="group123",
    bot_type="gemini",
    user_id="user456",
    timestamp=None  # Defaults to now
)
```

---

## Conversation Example: Mixed Memory Access

```
User: [Sends PDF: Spec.pdf]
User: @gemini Summarize this.
Gemini: (Context: Has Spec.pdf) Summary is...

[30 turns later...]

User: @gemini What was in that PDF we looked at earlier?
# Context: Spec.pdf has been truncated from the hot window.
Gemini: I am sorry, I no longer have the "Spec.pdf" in my active context. 

User: @gemini Check the archive for the PDF sent by me today.
Gemini: (Triggers search_archive) 🔍 Found "Spec.pdf". 
        (Retrieves file content) Based on the archive, the PDF contains...
```

## Key Decision Points

| Question | Current Strategy | Alternatives |
|-----|---------|---------|
| When to truncate? | Exceeds 20 messages or 8000 characters | Configurable |
| What to truncate? | Earliest messages | Based on importance |
| Share between Bots? | No (isolated by bot_type) | Share all |
| Codebase Persistence | Persists across /new | Reset on /new |
| Custom Prompts | Per bot, persisted | Per chat only |

## For Consideration

1. **Summary Chain**: Use small-scale summaries of truncated turns to extend "perceived" context.
2. **Pinned Context**: Allow users to explicitly "pin" a file or message so it never truncates.
3. **Cross-Group Search**: Should a user be able to search archives of Group A while in Group B? (Current: Prohibited for security).
4. **Prompt Templates**: Pre-defined prompt templates users can select from.
