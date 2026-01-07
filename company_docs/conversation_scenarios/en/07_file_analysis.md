# Scenario 07: File Analysis (PDF/Images)

## Scenario Description

The user sends a file (PDF, image, etc.), and the AI analyzes the file content to answer questions.

## Supported File Types

| Type | Gemini | ChatGPT | Grok |
|-----|--------|---------|------|
| PDF | ✅ | ❌ | ❌ |
| Images | ✅ | ✅ | ✅ |
| Docs | ✅ | ❌ | ❌ |

## Conversation Example

### PDF Analysis
```
User: [Sends PDF file: Financial Report.pdf]
User: @gemini What is the main content of this report?
Gemini: This is a financial report for the third quarter of 2024. The main points include:
        1. Revenue grew by 15% year-on-year.
        2. Net profit reached XXX thousand RMB.
        3. ...

User: @gemini What were the major expenditure items for the third quarter?
Gemini: According to page 12 of the report, major expenditures for Q3 included:
        1. R&D Investment: XXX thousand RMB (30%)
        2. Marketing: XXX thousand RMB (20%)
        ...
```

### Image Analysis
```
User: [Sends screenshot: Error Page.png]
User: @gemini What is the reason for this error?
Gemini: An HTTP 500 error can be seen in the screenshot...
        This is typically a server internal error, likely reasons:
        1. Database connection failure.
        2. Uncaught code exception.
        ...
```

### Multi-image Analysis
```
User: [Sends Image 1: UI Design-Homepage.png]
User: [Sends Image 2: UI Design-Details.png]
User: @gemini Is the design style consistent across these two pages?

Gemini: Analyzing these two design drafts:
        
        **Consistency Analysis**
        - Color System: Both pages use a blue primary color ✅
        - Fonts: Titles use Source Han Sans ✅
        - Spacing: Detail page spacing is slightly larger, recommend unifying ⚠️
        ...
```

## File Context Mechanism

### Saving Files
```python
# When a user sends a file
context_manager.save_file(
    chat_id=chat_id,
    sender_id=user_id,
    sender_name=user_name,
    file_uri="base64:...",    # or Cloud URI
    filename="Financial Report.pdf",
    mime_type="application/pdf",
    wecom_msg_id=msg_id,      # Used for reference matching
)
```

### 10-Minute Automatic Context
```python
# Check for files within the last 10 minutes
file_ctx = context_manager.get_active_file(chat_id, limit=50)

if file_ctx:
    elapsed_minutes = (time.time() - file_ctx["timestamp"]) / 60
    if elapsed_minutes > 10:
        file_ctx = None  # Exceeded 10 minutes, ignore
```

### Quoting a Specific File
```
User: [Quotes a previously sent PDF]
User: @gemini Summarize this document
# Explicit quote, will be used even if beyond 10 minutes
```

## Multi-turn File Conversation

### Follow-up Questions
```
User: [Sends PDF]
User: @gemini Summarize this

Gemini: This is a document about...

User: @gemini What is discussed in Chapter 3?
# Within 10 minutes, automatically use the same file
Gemini: Chapter 3 mainly discusses...

[Wait 15 minutes]

User: @gemini What about Chapter 4?
# Beyond 10 minutes, file context has expired
Gemini: Hello! Please send the document you need analyzed first, or quote the previous file message.
```

### Switching Files
```
User: [Sends FileA.pdf]
User: @gemini Summarize FileA
Gemini: FileA is a...

User: [Sends FileB.pdf]
User: @gemini Summarize FileB
Gemini: FileB is a...

User: @gemini What is the difference between FileA and FileB?
# Only FileB is within active automatic context
# FileA needs to be accessed via quoting

User: [Quotes the message for FileA]
User: @gemini Compare these two files
Gemini: Comparative analysis:
        - FileA: ...
        - FileB: ...
```

## LLM Invocation Method

### Gemini - Native File Support
```python
response = router.chat_with_file(
    provider="gemini",
    text="Summarize this document",
    file_data=file_bytes,
    file_mime_type="application/pdf",
    filename="Document.pdf",
    history=history_messages,
    system_prompt=system_prompt,
)
```

### OpenAI - Image Vision
```python
# Only supports images, not PDF
response = router.chat(
    provider="openai",
    messages=[
        {"role": "user", "content": [
            {"type": "text", "text": "Describe this image"},
            {"type": "image_url", "image_url": {"url": image_url}}
        ]}
    ]
)
```

## Key Decisions

| Decision Point | Current Solution | Alternatives |
|-------|---------|---------|
| Automatic Context Validity | 10 Minutes | Configurable |
| File Storage | Base64 or Cloud URI | Unified Cloud Storage |
| Multi-file Support | Most recent 1 | Support multiple simultaneous files |
| Unsupported Formats | Silent ignore | Prompt the user |

## To Be Considered

1. **Large File Handling**: How to handle files exceeding 10MB?
2. **File Pre-processing**: Is OCR or text extraction required?
3. **Multi-file Context**: Maintain context for multiple files simultaneously?
