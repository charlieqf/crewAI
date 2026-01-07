# Scenario 10: Context Reset

## Scenario Description

Users reset the conversation context through commands, clearing history or file associations.

## Core Commands

| Command | Function | Clearing Scope |
|-----|------|---------|
| `/reset` | Complete Reset | Conversation History + File Context + Codebase Context |
| `/new` | Clear File Context | Only file associations, retains conversation history |

## Conversation Example

### /reset - Complete Reset
```
[Previously had 15 conversation turns]
User: @gemini /reset
Gemini: ✅ Completely reset all conversation history and context (deleted 15 historical records)
        🔄 It is now a fresh start, and the bot no longer remembers any previous conversations.

User: @gemini Do you remember what we discussed earlier?
Gemini: Hello! This is our first conversation. How can I help you?
```

### /new - Clear File Context
```
User: [Sends PDF: Report.pdf]
User: @gemini Summarize this document
Gemini: This is a report about...

User: @gemini /new
Gemini: ✅ File context cleared, starting a new conversation
        💡 Previous files will no longer be used automatically; if needed, please resend or Quote them.

User: @gemini What did that report say just now?
Gemini: Based on our earlier conversation, the report mainly discussed...
        # Conversation history retained, knows the report was discussed
        
User: @gemini Continue analyzing Chapter 3 of the report
Gemini: Hello! Please send the document you need analyzed first, or quote the previous file message.
        # File context cleared, cannot directly access the PDF
```

## Content Cleared by /reset

```python
def handle_reset_command(chat_id):
    # 1. Clear message history
    deleted_count = context_manager.clear_context(chat_id)
    
    # 2. Clear file context
    context_manager.clear_file_context(chat_id)
    
    # 3. Clear codebase context
    if chat_id in _user_project_context:
        del _user_project_context[chat_id]
    
    return f"Deleted {deleted_count} historical records"
```

## Content Cleared by /new

```python
def handle_new_command(chat_id):
    # Only clear file associations
    success = context_manager.clear_file_context(chat_id)
    # Conversation history retained
    return success
```

## Usage Scenarios

### Scenario 1: Switching Topics
```
User: [Discussing Python project]
User: @gemini /new
User: [Sends new Java file]
User: @gemini Analyze this Java code
# Avoids Python context interference with Java analysis
```

### Scenario 2: Privacy Clearing
```
User: [Discussing sensitive business data]
User: @gemini Analyze this data
Gemini: ...

User: @gemini /reset
# Ensures sensitive data is no longer kept in context
```

### Scenario 3: Debugging
```
User: @gemini This answer is incorrect; are you influenced by the previous context?
User: @gemini /reset
User: @gemini [Asks again]
# Eliminates context interference
```

## Clearing Confirmation

### Current: No Confirmation
```
User: @gemini /reset
Gemini: ✅ Reset completed...
# Executes directly without confirmation
```

### Alternative: Requires Confirmation
```
User: @gemini /reset
Gemini: ⚠️ This will delete 15 historical records. Confirm? Reply Y to confirm.
User: Y
Gemini: ✅ Reset completed...
```

## Automatic Clearing Strategy

### Current: No Automatic Clearing
```python
# All messages are permanently retained (unless manually /reset)
```

### Alternative: Regular Cleanup
```python
# Messages older than 30 days are automatically cleaned up
# Keep only the last 100 messages
```

## Key Decisions

| Decision Point | Current Solution | Alternatives |
|-------|---------|---------|
| Confirmation Mechanism | No confirmation required | Sensitive operations require confirmation |
| Automatic Cleanup | None | Regular cleanup |
| Clearing Granularity | Group chat level | User + Group chat level |
| Undo Operation | Non-reversible | Recoverable within 7 days |

## To Be Considered

1. **Undo Feature**: Is an `/undo` command needed to revert deletion?
2. **Selective Clearing**: Clear records only for a specific time period?
3. **Export Feature**: Export conversation records before clearing?
4. **Custom Retention Period**: Allow setting automatic cleanup cycles?
