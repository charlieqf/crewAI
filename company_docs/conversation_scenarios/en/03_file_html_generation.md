# Scenario 03: HTML File Generation (/file-html)

## Scenario Description

Users request the AI to generate HTML files via the `/file-html` command, with the output being a cloud link.

## Core Requirements

1. **Use Full Context**: `/file-html` should not reduce conversation history.
2. **Change Output Format Only**: From text reply to file link.
3. **No Impact on Subsequent Conversations**: After using `/file-html`, subsequent normal conversations proceed normally.

## Conversation Example

### Basic File Generation
```
User: @gemini /file-html Make a login page
Gemini: Cloud Link: http://wecomfile.medmeeting.com/wecom/xxx.html
```

### Context-based Generation
```
User: @gemini Our company's brand color is blue #2563EB, and the Logo is a golden shield.
Gemini: Okay, I've recorded your brand information...

User: @gemini /file-html Help me make a login page that matches the brand tone.
Gemini: Cloud Link: http://wecomfile.medmeeting.com/wecom/xxx.html
# The generated page uses blue #2563EB and the golden shield element
```

### Normal Request Without /file-html
```
User: @gemini Help me design a layout for a login page
Gemini: Okay, here is a layout suggestion for a login page:
        1. Left side: Brand display area...
        2. Right side: Login form...
        (Plain text reply, no file generated)
```

## Implementation Mechanism

### Command Detection
```python
# In _handle_prompt_command
elif command == "file-html":
    return {
        "file_output_mode": True,
        "user_request": args.strip(),
        "continue_with_llm": True,  # Not a terminal command, continue with LLM flow
    }
```

### System Prompt Enhancement
```python
# When file_output_mode == True
if file_output_mode:
    file_instruction = (
        "\n\n[IMPORTANT: File Output Mode]\n"
        "The user requested output in the form of an HTML file. Please:\n"
        "1. Generate the response content as a complete HTML file\n"
        "2. Wrap the HTML content with <FILE name=\"output.html\">...</FILE> tags\n"
        "3. Use Tailwind CSS CDN for styling\n"
        "4. Output only the file, do not add extra explanations"
    )
    system_prompt = system_prompt + file_instruction
```

### Response Handling
```python
# In _process_llm_file_output
if file_only_mode:
    return f"Cloud Link: {qiniu_url_display}"
else:
    return f"\n\n[File Generated: {filename}]\nCloud Link: {qiniu_url_display}"
```

## Message Flow Diagram

```
User: "@gemini /file-html Make a login page"
           │
           ▼
┌─────────────────────────┐
│ Detect /file-html       │
│ file_output_mode = True │
│ content = "Make a page" │
└───────────┬─────────────┘
           │
           ▼
┌─────────────────────────┐
│ Get full history        │
│ (Normal context flow)   │
└───────────┬─────────────┘
           │
           ▼
┌─────────────────────────┐
│ System Prompt + File    │
│ instructions + Context  │
└───────────┬─────────────┘
           │
           ▼
┌─────────────────────────┐
│ Call LLM                │
│ Output: <FILE>...</FILE>│
└───────────┬─────────────┘
           │
           ▼
┌─────────────────────────┐
│ _process_llm_file_output│
│ file_only_mode = True   │
│ → Return cloud link only│
└───────────┬─────────────┘
           │
           ▼
User sees: "Cloud Link: http://..."
```

## Expected Behavior Table

| User Input | Expected Output |
|---------|---------|
| `/file-html Login page` | Cloud link |
| `Help me make a login page` | Text description (no file) |
| `/file-html` (no arguments) | Error prompt: Please provide generation requirements |

## Open Questions

1. **File Naming**: Do we support `/file-html:mypage.html` for custom filenames?
2. **File Type Expansion**: Do we need `/file-css`, `/file-js`, etc.?
3. **Error Handling**: What to do if the LLM fails to generate `<FILE>` tags?
