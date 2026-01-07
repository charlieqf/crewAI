# Scenario 07: File Analysis (PDF/Images)

## Scenario Description

The user sends a file (PDF, image, etc.), and the AI analyzes the file content to answer questions.

## Supported File Types & Bot Fallbacks

| Type | Gemini | ChatGPT | Grok | Fallback Behavior |
|-----|--------|---------|------|-------------------|
| **Images** | ✅ Native | ✅ Vision | ✅ Vision | None regular. |
| **PDF** | ✅ Native | ⚠️ Fallback | ❌ Unsupported | Non-Gemini bots use tools to extract text/links. |
| **Docs** | ✅ Native | ❌ Unsupported | ❌ Unsupported | Bot prompts: "Please send as PDF or text." |

### Policy: Bot Capability Fallback
If a user sends a file type not natively supported by the targeted bot:
1. **Tool-based Extraction**: If the bot has access to a `FileOCR` or `PDFParser` tool, it will attempt to use it first.
2. **User Prompt**: If no tool is available, the bot **must** reply with:
   > "I've received your file: {filename}, but as {bot_type}, I cannot analyze {mime_type} files directly. Please try @gemini or send the content as plain text."

---

## Multi-file Handling & Selection Rules

When a chat contains multiple files, the system uses the following **Selection Rule Priority**:

1. **Explicit Quote (Highest)**: If the user message quotes a specific file message, use that file.
2. **Most Recent (Default)**: If no quote, use the file sent within the last 10 minutes that is closest to the `@mention` message.
3. **Ambiguity Resolution**: If two different files were sent simultaneously or the context is unclear:
   - The bot should **ask the user** to clarify or quote the specific file.

### Example: Multi-file Comparison
```
User: [Sends Image: Layout_V1.png]
User: [Sends Image: Layout_V2.png]
User: @gemini Compare these two images.

# Selection Logic: The bot sees two active files in the 10-minute window.
Gemini: I see two images: "Layout_V1.png" and "Layout_V2.png". I will analyze both to provide a comparison.
```

---

## Conversation Example

### PDF Analysis (Non-Gemini Fallback)
```
User: [Sends PDF file: Financial Report.pdf]
User: @chatgpt What is the main content?

# Logic: ChatGPT doesn't support PDF Native. It triggers a PDF tool if available.
ChatGPT: 🔍 Parsing PDF "Financial Report.pdf"...
         Based on the extracted text, this report covers...
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

Gemini: Analyzing these two design drafts:
        
        **Consistency Analysis**
        - Color System: Both pages use a blue primary color ✅
        - Fonts: Titles use Source Han Sans ✅
        - Spacing: Detail page spacing is slightly larger, recommend unifying ⚠️
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
    
    return recent_files[0] # Return the most recent
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
| Selection Logic | Quote > Most Recent | Always ask |
| Unsupported Formats | Prompt the user with fallback advice | Silent ignore |
| Multi-file Support | Up to 10 files in context | Limit to 1 |

## For Consideration

1. **OCR for non-Gemini**: Should we build a heavy OCR service for non-native bots?
2. **Permanent Files**: Allowing `/pin_file` to keep a document in context indefinitely.
