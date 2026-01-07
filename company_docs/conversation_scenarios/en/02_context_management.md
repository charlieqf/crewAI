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

## Memory Model: Hot vs. Cold Storage

| Memory Type | Storage | Capacity | Access Rule (Decision Logic) |
| :--- | :--- | :--- | :--- |
| **Short-term (Context)** | Hot (chat_storage.db) | Recent 20 turns | Used for **immediate flow**. Automatically injected into LLM prompt. |
| **Long-term (Archive)** | Cold (chat_history.db) | Years / Unlimited | Used for **historical recall**. Must be retrieved via `ArchiveSearchTool`. |

### Decision Rule: When to Use Archive vs. Context

- **Scenario: Recall**
  - "What did we say just now?" -> **Context** (within the 20-turn window).
  - "What was the API key mentioned last week?" -> **Archive** (triggers tool).
- **Scenario: Summary**
  - "Summarize our conversation so far" -> **Context** (summarizes the hot window).
  - "Generate a weekly report for this group" -> **Archive** (requires scanning all messages).
- **Scenario: Continuity**
  - "Keep going" -> **Context** (relies on previous turn).

---

## Context Contamination & Persistence Policy

### 1. The /reset vs. /new Policy

| Command | Status | Clears Chat History? | Clears File Context? | Clears Codebase Context? |
| :--- | :--- | :--- | :--- | :--- |
| `/reset` | Global Reset | ✅ Yes | ✅ Yes | ✅ Yes |
| `/new` | Logical Break | ❌ No | ✅ Yes | ❌ No |

> [!NOTE]
> **Codebase context (`/codebase`) persists across `/new`** because it is often considered an "environment setting" for the current project session, whereas files are often "focal points" for a specific sub-topic.

### 2. Multi-Bot Context Sharing
- **Policy**: All bots in the same group chat **share the same short-term context**.
- **User Intent**: If you talk to `@gemini` and then `@chatgpt`, ChatGPT will see Gemini's previous responses. 
- **Contamination Risk**: If you want a bot to start fresh without seeing what another bot said, use `/reset` or `/new` (depending on whether you want to clear text history or just files).

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
| Share between Bots? | Yes (same chat_id) | Isolate by bot_type |
| Codebase Persistence | Persists across /new | Reset on /new |

## For Consideration

1. **Summary Chain**: Use small-scale summaries of truncated turns to extend "perceived" context.
2. **Pinned Context**: Allow users to explicitly "pin" a file or message so it never truncates.
3. **Cross-Group Search**: Should a user be able to search archives of Group A while in Group B? (Current: Prohibited for security).
