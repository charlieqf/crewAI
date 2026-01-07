# Scenario 04: Iterative File Refinement

## Scenario Description

After generating a file, the user wants to refine it based on previous results, such as "redo a version" or "change to a fintech style".

## Core Requirements

1. **Support Iterative Refinement**: Users can modify based on previous files.
2. **Retain Full Context**: AI knows what was generated before.
3. **Understand Refinement Instructions**: e.g., "redo", "improve", "change style".

## Conversation Example

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

### Mixing Conversation and File Generation
```
User: @gemini What are the typical characteristics of fintech style?
Gemini: Fintech style usually has following features:
        1. Dark background with bright accents
        2. Tech-feel gradients...
        (Plain text reply)

User: @gemini /file-html Redesign the login page according to this style
Gemini: Cloud Link: http://wecomfile.medmeeting.com/wecom/v4.html
# AI generates combining previous fintech style discussion
```

## File Information in Context

### Saving File Context
```python
# Save to context when generating a file
context_manager.save_file(
    chat_id=chat_id,
    sender_id=f"bot_{bot_type}",
    sender_name=bot_type,
    file_uri=cloud_url,       # Cloud link
    filename=filename,         # output.html
    mime_type="text/html",
)

# Also save as a message
context_manager.add_message(
    chat_id=chat_id,
    content=f"Cloud Link: {cloud_url}",  # Reply content
    role="assistant",
)
```

### Context Seen by LLM
```python
messages = [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "Make a login page"},
    {"role": "assistant", "content": "Cloud Link: http://.../v1.html"},
    {"role": "user", "content": "Redo a version, change style to fintech"},  # Current
]
```

## Key Issues

### Issue 1: How does the AI "remember" previous file content?

**Current Solution**:
- AI only sees the text reply "Cloud Link: xxx".
- AI cannot access the actual HTML content of the file.
- However, AI has the full conversation history and knows what the user previously requested.

**Potential Problem**:
```
User: @gemini /file-html Change title from "Welcome" to "Login System"
# AI doesn't know the current title is "Welcome", might not modify accurately
```

**Improvement Option A - Save HTML Summary**:
```python
# Save a summary when generating the file
context_manager.add_message(
    content=f"[Generated HTML file]\nSummary: Login page, blue theme, contains title 'Welcome', forms...",
    role="assistant",
)
```

**Improvement Option B - Reference File Content**:
```python
# User can Quote the file to let AI read content
User: [Quotes previous cloud link message]
User: @gemini /file-html Based on this file, change title to "Login System"
```

### Issue 2: How to distinguish between multiple files?

```
User: @gemini /file-html Login page
Gemini: Cloud Link: http://.../login.html

User: @gemini /file-html Registration page
Gemini: Cloud Link: http://.../register.html

User: @gemini /file-html Improve login page
# How does the AI know which one to improve?
```

**Solution**:
1. Explicitly specify: "Improve the previous login page"
2. Quote message: Quote the cloud link for the login page

## Design Decisions

| Decision Point | Current Solution | Alternatives |
|-------|---------|---------|
| Retain file content | Link only | Save HTML summary |
| Refinement recognition | Rely on conversation history | Explicit file versioning |
| Distinguish multiple files | User explicitly specifies | File tagging system |

## To Be Implemented

1. **File Content Summary**: Automatically generate summaries to save in context when creating files.
2. **Version Association**: Link multiple versions of the same file.
3. **Diff Preview**: Show change points during refinement.
