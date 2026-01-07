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

## Conversation Example: Long Conversation Truncation

```
# Assuming there are already 19 historical messages

User: @gemini 20th message
Gemini: Reply to the 20th

User: @gemini 21st message
# At this point, the 1st message is removed
# LLM only sees messages 2-21
Gemini: Reply to the 21st

User: @gemini Do you remember what we discussed at the very beginning?
Gemini: Sorry, I cannot recall the earlier conversation content...
```

## Conversation Example: Manual Reset

### /reset - Complete Reset
```
User: @gemini /reset
Gemini: ✅ Completely reset all conversation history and context (deleted 15 historical records)
        🔄 It is now a fresh start, and the bot no longer remembers any previous conversations.

User: @gemini What did we discuss earlier?
Gemini: Hello! This is our first conversation. How can I help you?
```

### /new - Clear File Context
```
User: [Sends a PDF file]
User: @gemini Summarize this document
Gemini: This is a document about...

User: @gemini /new
Gemini: ✅ File context cleared, starting a new conversation
        💡 Previous files will no longer be used automatically; if needed, please resend or Quote them.

User: @gemini Help me summarize the document
Gemini: Hello! Please send the document you need summarized first.
# File context has been cleared, but conversation history remains
```

## Context Isolation

### Isolation by chat_id
```
Group Chat A (chat_id: group_A):
  User 1: Discusses Python
  Gemini: Python is...
  
Group Chat B (chat_id: group_B):
  User 2: Discusses JavaScript
  Gemini: JavaScript is...
  
# The context of the two group chats is completely independent.
```

### Sharing Across Bots
```
Group Chat A:
  User: @gemini What is Python?
  Gemini: Python is a programming language...
  
  User: @chatgpt Continue explaining
  ChatGPT: Okay, continuing from the previous topic, Python...
  
# Different Bots in the same group chat share context
# (Because the chat_id is the same)
```

## Key Decision Points

| Question | Current Strategy | Alternatives |
|-----|---------|---------|
| When to truncate? | Exceeds 20 messages or 8000 characters | Configurable |
| What to truncate? | Earliest messages | Based on importance |
| Share between Bots? | Yes (same chat_id) | Isolate by bot_type |
| Reset granularity? | /reset clears all, /new only files | More granular options |

## For Consideration

1. **Summary Mechanism**: Do extra-long conversations need automatic summarization?
2. **Important Message Tagging**: Should certain messages be kept permanently?
3. **User Preferences**: Allow users to set context length?
