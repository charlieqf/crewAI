# Scenario 05: GitLab Code Review

## Scenario Description

When a user sends a GitLab Commit URL, the AI automatically triggers the code review process.

## Trigger Conditions

### URL Format
```
https://<domain>/<project-path>/-/commit/<sha>
```

### Trigger Rules
1. **URL + Keywords**: `review`, `审查`, `审核`, `检查`, `看看`, `帮我看`
2. **URL Only**: If the message contains only a commit URL, it triggers automatically.
3. **Exclusion Rules**: If the message contains `不要审查` or `别审查`, it will not trigger.

## Conversation Example

### Automatic Trigger
```
User: @gemini https://gitlab.example.com/project/-/commit/abc123
Gemini: 🔍 Reviewing commit abc123...
        
        ## Code Review Report
        
        **Change Summary**
        - Modified 3 files
        - Added 45 lines, deleted 12 lines
        
        **Findings**
        1. ⚠️ SQL injection risk...
        2. 💡 Suggested optimization...
```

### With Keywords
```
User: @gemini Help me look at this commit https://gitlab.example.com/project/-/commit/abc123
Gemini: 🔍 Reviewing commit abc123...
        [Review Report]
```

### No Trigger
```
User: @gemini The link for this commit is https://gitlab.example.com/project/-/commit/abc123, but don't review it, just recording it.
Gemini: Okay, I have recorded the commit link.
```

## Multi-turn Conversation Example

### Follow-up After Review
```
User: @gemini https://gitlab.example.com/project/-/commit/abc123
Gemini: [Review Report: SQL injection risk found...]

User: @gemini What exactly is the problem with this SQL injection?
Gemini: In the code you submitted, line 42 uses string concatenation to build the SQL query...
        It's recommended to use parameterized queries...

User: @gemini Can you give an example of how to fix it?
Gemini: Of course, here is the modified code:
        ```python
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        ```
```

### Sequential Review of Multiple Commits
```
User: @gemini https://gitlab.example.com/project/-/commit/abc123
Gemini: [Review Report 1]

User: @gemini How about this one? https://gitlab.example.com/project/-/commit/def456
Gemini: [Review Report 2]

User: @gemini Is there any connection between these two commits?
Gemini: Based on the review results, these two commits seem related:
        - Commit abc123 added the user authentication feature.
        - Commit def456 fixed a bug in the authentication logic...
```

## Code Review Flow

### Architecture
```
User Message
    │
    ▼
┌─────────────────┐
│ Detect GitLab URL │
│ Detect Keywords   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ CodeReviewFlow  │
│ (CrewAI Agent)  │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌───────┐ ┌────────┐
│ Get   │ │ Get    │
│ Commit│ │ Diff   │
│ Info  │ │ Content│
└───┬───┘ └───┬────┘
    │         │
    └────┬────┘
         ▼
┌─────────────────┐
│ LLM Code Analysis│
│ Generate Report │
└────────┬────────┘
         │
         ▼
    Review Report
```

### Agent Configuration
```python
code_review_agent = Agent(
    role="Code Review Expert",
    goal="Discover issues and improvement points in code",
    backstory="Senior code reviewer, familiar with security, performance, maintainability, etc.",
)
```

## Context Storage

```python
# Save review report as an assistant message
context_manager.add_message(
    chat_id=chat_id,
    content=review_report,
    role="assistant",
    bot_type=bot_type,
)
```

## Key Decisions

| Decision Point | Current Solution | Alternatives |
|-------|---------|---------|
| Trigger Method | URL Detection + Keywords | Explicit /review command |
| Review Depth | Automatic judgment | Configurable levels |
| Report Format | Markdown text | HTML file |
| History Tracking | Save to context | Independent review records |

## To Be Considered

1. **Private Repository Auth**: How to securely handle the GitLab Token?
2. **Large Commits**: How to handle changes exceeding 1000 lines?
3. **Review Templates**: Should custom review templates be supported?
