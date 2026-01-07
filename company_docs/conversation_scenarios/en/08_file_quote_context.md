# Scenario 08: File Quoting and Context

## Scenario Description

Users explicitly specify a file to analyze using the Quote feature, overriding the automatic context.

## Quote Mechanism

### WeCom Message Quote
```json
{
  "msgtype": "text",
  "text": {
    "content": "@gemini Analyze this file"
  },
  "quote": {
    "quoted_content": "Financial Report.pdf",
    "quoted_msg_id": "msg_12345"
  }
}
```

### Quote Matching Logic
```python
# 1. Attempt matching by msg_id
file_ctx = context_manager.get_active_file(
    chat_id, 
    wecom_msg_id=quoted_msg_id
)

# 2. Fallback: Match by filename
if not file_ctx:
    file_ctx = context_manager.get_active_file(
        chat_id, 
        filename=quoted_filename
    )
```

## Conversation Example

### Quoting an Expired File
```
[1 hour ago]
User: [Sends PDF: Project Plan.pdf]
User: @gemini Summarize this document
Gemini: This is a project plan...

[Now]
User: Yes, that's the file.
User: [Quotes the previous PDF message]
User: @gemini What are the milestones for this project?
# Accessible via Quote even after 10 minutes
Gemini: According to the "Project Plan", the main milestones include:
        1. Requirements phase: End of March
        2. Design phase: Mid-April
        ...
```

### Quoting a Specific Message
```
User: [Sends Image A: Mockup.png]
User: @gemini What do you think of this design?
Gemini: The layout is clear...

User: [Sends Image B: Final Draft.png]
User: @gemini This version is better
Gemini: Yes, the final draft has these improvements...

User: [Quotes Image A message]
User: @gemini Compared to the first version, what are the changes?
# Explicitly quotes Image A, while Image B is in automatic context
Gemini: Comparing the two versions:
        - Image A (Mockup): Basic layout...
        - Image B (Final Draft): Added colors...
```

### Quoting Text Messages
```
User: Our company Logo is a golden shield, and the brand color is dark blue.
Gemini: Okay, recorded.

[After many turns]

User: [Quotes the message about the Logo]
User: @gemini /file-html Make a page that matches this brand
Gemini: Cloud Link: http://.../branded_page.html
# The quoted text message content is included in the context
```

## Quote Priority

```
Quoted File (Quote)  →  Highest Priority
        ↓
Automatic Context File (Within 10 mins)  →  Secondary Priority
        ↓
No File Context  →  Plain Text Conversation
```

## Code Implementation

### Quote Content Extraction
```python
def _extract_quote_content(data: dict) -> tuple[str | None, str | None]:
    """Extract quoted message content and message ID"""
    quote = data.get("quote", {})
    quoted_content = quote.get("quoted_content")
    quoted_msg_id = quote.get("quoted_msg_id")
    return quoted_content, quoted_msg_id
```

### Merging Context
```python
# The quoted content is added to the user message
if quoted_content:
    if original_content:
        content = f"[User quoted message: {quoted_content}]\n\nUser Question: {original_content}"
    else:
        content = f"The user quoted the following message and @mentioned you. Please respond based on the quoted content:\n\n{quoted_content}"
```

## Boundary Cases

### Quoting a Cleaned-up File
```
User: [Quotes an expired file]
User: @gemini Analyze this

# File has been cleaned up on the server
Gemini: Sorry, this file may have expired or is unavailable. Please resend the file.
```

### Quoting Someone Else's Message
```
Colleague A: [Sends file]
Colleague A: @gemini Look at this

User: [Quotes Colleague A's file message]
User: @gemini Analyze this for me too
# Quoting across users is allowed within the same group chat
Gemini: Based on the file analysis...
```

### Quoting Bot's Reply
```
User: @gemini Write a piece of code
Gemini: ```python def foo(): pass ```

User: [Quotes Gemini's reply]
User: @gemini Explain this code
Gemini: This code defines a function named foo...
```

## Key Decisions

| Decision Point | Current Solution | Alternatives |
|-------|---------|---------|
| Quote Matching | msg_id first, filename fallback | msg_id only |
| Expired Files | Inaccessible | Re-download |
| Cross-user Quote | Allowed within group | Only own files |
| Quote Format | Added to message content | Independent context |

## To Be Considered

1. **Quote Chains**: How to handle when the quoted message is itself a quote?
2. **Batch Quotes**: Quoting multiple messages at once?
3. **Quote Preview**: How is the preview of quoted content generated?
