# Scenario 01: Basic Multi-turn Conversation

## Scenario Description

Users engage in normal multi-turn conversations with the AI, without special commands or files.

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
- Every message is saved to the SQLite database.
- Fields: `chat_id`, `sender_id`, `sender_name`, `content`, `role`, `timestamp`

### Context Construction
```python
# During each LLM call
messages = [
    {"role": "system", "content": "You are a helpful assistant..."},
    {"role": "user", "content": "Hello, I'd like to learn about Python decorators."},
    {"role": "assistant", "content": "Hello! A Python decorator is..."},
    {"role": "user", "content": "Can you give an example?"},
    {"role": "assistant", "content": "Sure, here is a simple example..."},
    {"role": "user", "content": "What is the execution order when there are multiple decorators?"},  # Current message
]
```

### Limit Strategy
- **max_messages = 20**: Keep at most 20 historical messages.
- **max_chars = 8000**: Up to 8000 characters.
- When limits are exceeded, removal starts from the earliest messages.

## Key Code

```python
# chat_context.py
class ChatContextManager:
    def get_messages_for_llm(self, chat_id, system_prompt=None):
        # Fetch historical messages from DB
        # Apply sliding window limits
        # Format into LLM message format
        pass
```

## Expected Behavior

| User Action | System Behavior |
|---------|---------|
| Send normal message | Save to context → Build full message list → Call LLM → Save reply |
| Continuous dialogue | Each turn can access previous conversation history |
| Over 20 messages | Automatically remove the earliest message |

## Notes

1. **Responses should not contain files**: Normal conversations do not generate `<FILE>` tags.
2. **Clean System Prompt**: Does not contain any file generation instructions.
3. **Context isolation by group chat**: Different `chat_id`s are completely independent.
