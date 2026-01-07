# Scenario 11: Mixed Complex Scenarios

## Scenario Description

This scenario covers complex interactions combining multiple capabilities (codebase, file analysis, file generation, search).

---

## 1. Mixed Modality in One Turn

When a user sends a message containing text, a quote, a file, and an @mention in a single turn, the system merges them into a single coherent prompt for the LLM.

### Modality Merging Sequence (Prompt Construction)
1. **Quoted Message**: `[User quoted message: {content}]`
2. **File Context**: `[File Attachment: {filename} ({mime_type})]`
3. **User Input Text**: `{cleaned_text}` (after removing @mention and commands)

> [!IMPORTANT]
> **Command Stripping**: Any system command (e.g., `/reset`, `/set_prompt`, `/codebase`) is executed by the system and then **removed** from the text before it is sent to the LLM. This prevents the LLM from trying to "answer" the command itself.

### Example turn
```
User: [Quotes: "Deadline is next Monday"]
User: [Sends PDF: project_plan.pdf]
User: @gemini /set_prompt ... Based on the quoted deadline and this PDF, verify if we are on track.

# Merged Prompt sent to LLM:
# [User quoted message: Deadline is next Monday]
# [File Attachment: project_plan.pdf (application/pdf)]
# Verified prompt: Based on the quoted deadline and this PDF, verify if we are on track.
```

---

## 2. Command Collisions & Priorities

If multiple commands appear in a single message, the system follows a strict **execution order** rather than rejecting the message.

### Priority Table
| Order | Command Type | Action |
| :--- | :--- | :--- |
| **1st** | `/reset` | Clears everything first. |
| **2nd** | `/new` | Clears files if /reset wasn't present. |
| **3rd** | `/set_prompt` | Updates the persona. |
| **4th** | `/codebase` | Sets the project context. |
| **5th** | `/file-html` / `Content` | Triggers the actual task. |

### Example: Reset and Generate
```
User: @gemini /reset /file-html Make a landing page.

# Logic: 
# 1. System executes /reset (Clears context).
# 2. System then treats "/file-html Make a landing page" as a fresh request.
# Result: A landing page is generated with zero stale context interference.
```

### Example: Collision (Reject vs. Step)
If `/codebase` and `/file-html` are sent together:
- **Decision**: The system **supports both**. It first switches the codebase context, then uses that context to generate the HTML.

---

## 3. Advanced Multi-Turn Scenarios

### Scenario A: From Design to Implementation
```
User: [Sends image: Mockup.png]
User: @gemini /codebase myproject /file-html Implement this.
Gemini: 🔍 Setting codebase to `myproject`...
        🔍 Analyzing image content...
        Cloud Link: http://.../login_impl.html
```

### Scenario B: Cross-Bot Collaboration
```
User: @gemini /codebase myproject Analysis...
User: @chatgpt Evaluate Gemini's results...
# Context is shared via chat_id, allowing GPT to see Gemini's codebase analysis.
```

## Technical Challenges

1. **Token Overflow**: Merging text, quote, and multi-file context can quickly hit 128k/1M limits.
2. **Modality Order**: Does the image "describe" the text or vice-versa?

## Support Matrix

| Combination | Status | Priority Rule |
|-----|---------|-----|
| Text + File + Quote | ✅ | Construction: Quote > File > Text. Instruction: Text > File > Quote. |
| Multiple Commands | ✅ | Reset > Config > Task. |
| Mixed Modality | ✅ | Merged into structured prompt (commands stripped). |

---

## 4. Scenario F: Daily Visualized Report Generation (Archive + FileGen)

Users request a summary of the day's group chat content in the form of an HTML report, including topic summaries, to-dos, and precise navigation.

```
User: @gemini /file-html Based on today's group chat, generate an HTML report for me (including topic summaries, to-dos, achievements, and the ability to precisely locate single chat records).

Gemini: (1. Call Archive Tool to get today's messages)
        (2. Analyze and extract topics, todos, achievements)
        (3. Generate HTML report containing Tailwind CSS)
        
        Cloud Link: http://wecomfile.medmeeting.com/archive/daily_report_20250107.html
        
        **Report Features**:
        - 📊 **Visual Dashboard**: Displays activity trends using Chart.js
        - 📝 **Topic Cards**: Groups messages by topic
        - ✅ **To-do List**: Extracts tasks for @Usernames
        - 🔗 **Precise Location**: Includes `[View Original Message]` links after each summary
          (Implementation: Links point to `/archive/viewer?msgid=xxx` or use WeCom reference format)
```
