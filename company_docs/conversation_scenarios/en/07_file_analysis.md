# Scenario 07: File Analysis (PDF/Images)

## Scenario Description

The user sends a file (PDF, image, etc.), and the AI analyzes the file content to answer questions.

## Supported File Types & Bot Fallbacks

| Type | Gemini | ChatGPT | Grok | Fallback Behavior |
|-----|--------|---------|------|-------------------|
| **Images** | Vision | Vision | Vision attempt | If image decrypt fails, fall back to text-only. |
| **PDF** | File analysis enabled | File analysis enabled | Not supported | If analysis fails, fall back to text-only with a hint. |
| **Docs** | File analysis enabled | File analysis enabled | Not supported | If analysis fails, fall back to text-only with a hint. |

### Policy: Bot Capability Fallback
If a user sends a file type not natively supported by the targeted bot:
1. **File Context Skipped**: The bot does not load file content for analysis.
2. **Text-only Response**: The bot continues with normal text processing and may append a hint that file context was unavailable.

---

## Multi-file Handling & Selection Rules

When a chat contains multiple files, the system uses the following **Selection Rule Priority**:

1. **Explicit Quote (Highest)**: If the user message quotes a specific file message, use that file.
2. **Most Recent (Default)**: If no quote, use the latest file within the last 10 minutes.
3. **No Auto-Disambiguation**: If multiple files exist, the system still picks the most recent file. Users must quote a specific file to override.

### Example: Multi-file Comparison
```
User: [Sends Image: Layout_V1.png]
User: [Sends Image: Layout_V2.png]
User: @gemini Compare these two images.

# Selection Logic: The bot uses the most recent file unless a quote is provided.
Gemini: I will analyze "Layout_V2.png". If you want a comparison, please quote "Layout_V1.png".
```

---

## Conversation Example

### PDF Analysis (Fallback to Text)
```
User: [Sends PDF file: Financial Report.pdf]
User: @chatgpt What is the main content?

# Logic: File analysis is attempted; if it fails, fall back to text-only response.
ChatGPT: I cannot load the PDF content in this session. Please try @gemini or paste the key sections as text.
```

### Image Analysis
```
User: [Sends screenshot: Error Page.png]
User: @gemini What is the reason for this error?
Gemini: An HTTP 500 error can be seen in the screenshot...
```

### Multi-image Analysis
```
User: [Sends Image 1: UI Design-Homepage.png]
User: [Sends Image 2: UI Design-Details.png]
User: @gemini Is the design style consistent across these two pages?

Gemini: Analyzing the most recent design draft:
        
        **Consistency Analysis**
        - Color System: Both pages use a blue primary color (OK)
        - Fonts: Titles use Source Han Sans (OK)
        - Spacing: Detail page spacing is slightly larger, recommend unifying (Note)
        ...
```

## File Context Mechanism

### 10-Minute Automatic Context
Files are "active" for 10 minutes. After 10 minutes, they are removed from the automatic injection to save tokens and prevent "stale" context issues.

### Manual Override (Quote)
Explicitly quoting a file message bypasses the 10-minute rule.

---

## Technical Details

### Selection Rule Code Logic
```python
def get_target_file(chat_data):
    # 1. Check Quote
    if chat_data.quote:
        return resolve_by_msg_id(chat_data.quote.msg_id)
    
    # 2. Check Recent (10 min)
    recent_files = storage.get_recent_files(chat_data.chat_id, minutes=10)
    if not recent_files:
        return None
    
    # Return the most recent file only
    return recent_files[0]
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

### Vision - Image Support
```python
response = router.chat_with_image(
    provider=provider,
    text="Describe this image",
    image_base64=image_base64,
    system_prompt=system_prompt,
    history=history_messages,
    max_tokens=4096,
)
```

## Key Decisions

| Decision Point | Current Solution | Alternatives |
|-------|---------|---------|
| Selection Logic | Quote > Most Recent | Always ask |
| Unsupported Formats | Text-only fallback (hint on failure) | Prompt user explicitly |
| Multi-file Support | Single active file in context | Multi-file selection |

## For Consideration

1. **OCR for non-Gemini**: Should we build OCR or PDF parsing to avoid text-only fallback?
2. **Permanent Files**: Allowing `/pin_file` to keep a document in context indefinitely.
