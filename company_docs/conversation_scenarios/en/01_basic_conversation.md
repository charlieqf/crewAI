# Scenario 01: Basic Multi-turn Conversation

## Scenario Description

Users engage in normal multi-turn conversations with AI bots (gemini/chatgpt/grok), without special commands or files.

## Conversation Example

```
User: @gemini Hello, I'd like to learn about Python decorators.
Gemini: Hello! A Python decorator is... (explanation)

User: @gemini Can you give an example?
Gemini: Sure, here is a simple example... (code example)

User: @gemini What is the execution order when there are multiple decorators?
Gemini: Multiple decorators are executed from bottom to top... (explanation)
```

## Context Management

### Message Storage
- Every message is saved to the SQLite database via `ChatStorageTool`.
- Fields: `chat_id`, `sender_id`, `sender_name`, `content`, `role`, `timestamp`, `bot_type`, `storage_key`
- Each bot type (gemini/chatgpt/grok) maintains its own context per chat.

### Context Construction
```python
# During each LLM call via ChatContextManager.get_messages_for_llm()
messages = [
    {"role": "system", "content": "You are a helpful assistant..."},  # Or custom prompt
    {"role": "user", "content": "Hello, I'd like to learn about Python decorators."},
    {"role": "assistant", "content": "Hello! A Python decorator is..."},
    {"role": "user", "content": "Can you give an example?"},
    {"role": "assistant", "content": "Sure, here is a simple example..."},
    {"role": "user", "content": "What is the execution order when there are multiple decorators?"},
]
```

### Limit Strategy
- **max_messages = 20**: Keep at most 20 historical messages.
- **max_chars = 8000**: Up to 8000 characters total.
- When limits are exceeded, removal starts from the earliest messages.
- Limits are applied via sliding window in `get_context()`.

### Archive Context Injection (NEW)

> [!IMPORTANT]
> All normal conversations now **automatically inject 3 hours of archive context** from the group chat.

This allows the bot to access recent group discussions even if those messages weren't directly sent to the bot.

| Scenario | Archive Range | Includes |
|----------|---------------|----------|
| Normal conversation | **3h** (default) | Text messages + extracted file/image content |
| `/1d Question` | **1 day** | Same as above |
| `/1w Summary` | **1 week** | Same as above |

> [!NOTE]
> Default 3h injection respects `/reset` timestamp. Explicit `/Nd` commands bypass it. See [Context Management](02_context_management.md).

**Example:**
```
[10:00-12:00] Users A, B, C discuss a project (bot not mentioned)

[12:05] User A: @gemini Summarize what we just discussed
Gemini: Based on the recent discussion, you discussed... 
# Bot can access the 3h of archive context automatically
```

## Key Code

```python
# chat_context.py
class ChatContextManager:
    def __init__(
        self,
        db_path: str | None = None,
        max_messages: int = 20,
        max_chars: int = 8000,
    ):
        self.max_messages = max_messages
        self.max_chars = max_chars
        self.storage = ChatStorageTool(backend="sqlite", db_path=db_path)

    def get_messages_for_llm(
        self,
        chat_id: str,
        system_prompt: str | None = None,
        current_message: str | None = None,
        bot_type: str | None = None,
    ) -> list[dict]:
        # Fetch context (applies limits)
        context = self.get_context(chat_id, bot_type=bot_type)
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        # Add historical messages
        for msg in context.messages:
            messages.append({"role": msg["role"], "content": msg["content"]})
        
        # Add current message
        if current_message:
            messages.append({"role": "user", "content": current_message})
        
        return messages
```

## Expected Behavior

| User Action | System Behavior |
|-------------|-----------------|
| Send normal message | Save to context → Build message list → Call LLM → Save reply |
| Continuous dialogue | Each turn accesses previous conversation history |
| Over 20 messages | Automatically remove the earliest messages |
| Switch bot type | Each bot maintains separate context for the same chat |

## Notes

1. **Responses should not contain files**: Normal conversations do not generate `<FILE>` tags.
2. **Bot-specific context**: Different bots (gemini/chatgpt/grok) have isolated contexts even in the same chat.
3. **Context isolation by group chat**: Different `chat_id`s are completely independent.
4. **Custom prompts**: Users can set custom system prompts per chat+bot via `/set_prompt`, `/show_prompt`, `/reset_prompt` commands.
