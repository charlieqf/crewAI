# Scenario 03: HTML File Generation

## Scenario Description

Users request the AI to generate HTML files via file commands. The system supports free-form generation (`/file-html`), daily summary reports (`/file-html-daily`), and meeting minutes (`/file-html-meeting`).

## Available Commands

| Command | Purpose | Example |
|---------|---------|---------|
| `/file-html [time] <description>` | Free-form HTML generation | `/file-html Make a login page` |
| `/file-html-daily [time]` | Group chat summary report | `/file-html-daily 1w` |
| `/file-html-meeting [time]` | Meeting minutes | `/file-html-meeting 3h` |

### Time Range Parameters
- `1h`, `2h`, `3h` - Hours
- `1d`, `2d`, `3d` - Days
- `1w` - One week

## Core Requirements

1. **Use Full Context**: File commands should leverage conversation history and archive.
2. **Archive Integration**: For time-ranged requests, historical messages are injected from the archive.
3. **Auto-Fallback**: If LLM fails to generate `<FILE>` tags, system auto-wraps the content.

## Conversation Examples

### Basic File Generation
```
User: @gemini /file-html Make a login page
Gemini: Cloud Link: http://wecomfile.medmeeting.com/wecom/xxx.html
```

### Time-Ranged Generation
```
User: @gemini /file-html 1w Summarize this week's discussions
Gemini: Cloud Link: http://wecomfile.medmeeting.com/wecom/weekly_summary.html
# System injects 1 week of archive data into context
```

### Daily Summary Template
```
User: @gemini /file-html-daily 3d
Gemini: Cloud Link: http://wecomfile.medmeeting.com/wecom/daily_report.html
# Generates structured summary of last 3 days
```

### Meeting Minutes Template
```
User: @gemini /file-html-meeting
Gemini: Cloud Link: http://wecomfile.medmeeting.com/wecom/meeting_minutes.html
# Generates meeting notes with attendees, action items, etc.
```

## Implementation Mechanism

### Command Detection (commands.py)
```python
elif command == "file-html":
    # Supports time range: /file-html [1d|2d|1w] <description>
    time_pattern = re.match(r'^(\d+[hdw])\s+(.+)$', args, re.IGNORECASE)
    if time_pattern:
        time_range = time_pattern.group(1)
        user_request = time_pattern.group(2)
    else:
        time_range = None
        user_request = args
    
    return {
        "file_output_mode": True,
        "user_request": user_request,
        "date_range": time_range,
        "continue_with_llm": True,
    }
```

### System Prompt Enhancement (llm_orchestrator.py)
```python
if file_output_mode:
    file_instruction = (
        "\n\n[CRITICAL SYSTEM REQUIREMENT: FILE OUTPUT MODE]\n"
        "You MUST respond with:\n"
        "1. FIRST: A 1-sentence summary of what you're generating.\n"
        "2. CONTENT: The complete HTML content wrapped inside <FILE name=\"output.html\">...</FILE> tags.\n"
        "3. NOTHING else after the closing </FILE> tag.\n"
        "Failure to use the <FILE> tags will break the system integration.\n\n"
        "IMPORTANT EXAMPLE:\n"
        "<FILE name=\"report.html\"><html>...</html></FILE>"
    )
```

### Archive Context Injection
```python
if date_range and file_output_mode:
    logger.info(f"[AIBOT_FILE] Injecting archive context for file command, date_range={date_range}")
    # Fetches historical messages from chat_history.db and injects into prompt
```

### Auto-Wrap Fallback
```python
# If LLM doesn't generate <FILE> tags in file_only_mode
if file_only_mode and not file_pattern.search(llm_response):
    logger.info("[AIBOT_FILE] No <FILE> tags found, initiating auto-wrap fallback")
    # Wraps entire response in <FILE name="output.html">...</FILE>
```

## Message Flow Diagram

```
User: "@gemini /file-html 1w Write a summary"
           │
           ▼
┌─────────────────────────┐
│ Command Detection       │
│ file_output_mode = True │
│ date_range = "1w"       │
│ content = "Write..."    │
└───────────┬─────────────┘
           │
           ▼
┌─────────────────────────┐
│ Inject Archive Context  │
│ (if date_range set)     │
└───────────┬─────────────┘
           │
           ▼
┌─────────────────────────┐
│ System Prompt + File    │
│ Instructions + Context  │
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
│ Process Output          │
│ - Extract <FILE> tags   │
│ - Upload to Qiniu       │
│ - Auto-wrap if needed   │
└───────────┬─────────────┘
           │
           ▼
User sees: "Cloud Link: http://..."
```

## Expected Behavior Table

| User Input | Expected Output |
|------------|-----------------|
| `/file-html Login page` | Cloud link to generated HTML |
| `/file-html 1w Weekly summary` | Cloud link (with 1 week archive context) |
| `/file-html-daily` | Cloud link to daily summary template |
| `/file-html-meeting 3h` | Cloud link to meeting minutes (3 hour context) |
| `/file-html` (no arguments) | Error: ❌ 请提供生成描述 |
| `Help me make a login page` | Text description (no file) |

## Error Handling

| Scenario | System Behavior |
|----------|-----------------|
| LLM fails to generate `<FILE>` tags | Auto-wrap fallback triggers |
| Unclosed `<FILE>` tag | Takes content until end/next tag |
| Qiniu upload fails | Error logged, cloud link unavailable |
| No arguments provided | Returns usage instructions |

## Key Files

- `commands.py` - Command parsing and routing
- `llm_orchestrator.py` - LLM prompt construction and file processing
- Uses Qiniu CDN for file hosting
