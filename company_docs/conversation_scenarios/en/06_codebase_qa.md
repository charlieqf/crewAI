# Scenario 06: Codebase QA (/codebase)

## Scenario Description

After setting the codebase context, users can directly ask questions related to the code.

## Core Command

### /codebase - Set Codebase Context
```
/codebase <gitlab_url_or_project_path> [branch]
```

## Conversation Example

### Basic Usage
```
User: @gemini /codebase https://gitlab.example.com/myproject
Gemini: ✅ Codebase context set: `myproject`
        📌 Current branch: `main`
        
        Now you can ask questions directly, for example:
        - "In which files do these table names appear?"
        - "Where is the creditor_code field processed?"

User: @gemini Where is the user authentication logic implemented?
Gemini: According to code analysis, user authentication logic is mainly distributed in the following locations:
        
        1. `src/auth/authenticator.py` - Main authentication class
        2. `src/middleware/auth_middleware.py` - Middleware
        3. ...

User: @gemini What error code is returned when authentication fails?
Gemini: According to lines 78-92 in `src/auth/authenticator.py`...
        It returns a 401 error code when authentication fails...
```

### Specifying a Branch
```
User: @gemini /codebase myproject develop
Gemini: ✅ Codebase context set: `myproject`
        📌 Current branch: `develop`
```

### Inline Question
```
User: @gemini /codebase myproject What framework does this project use?
Gemini: 🔍 Analyzing `myproject` codebase (Branch: `main`)...
        
        The project uses the FastAPI framework, primarily depending on:
        - FastAPI 0.100.0
        - SQLAlchemy 2.0
        - ...
```

### Screenshot + Codebase
```
User: [Sends error screenshot]
User: @gemini Where in the code is this error coming from?
Gemini: Based on the error message "ConnectionResetError" in the screenshot...
        This error appears on line 45 of `src/database/connection.py`...
        We recommend adding a retry mechanism...
```

## Codebase QA Flow

### Architecture
```
User Question
    │
    ▼
┌─────────────────┐
│ Detect Codebase │
│ Context (Cache) │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ CodebaseQAFlow  │
│ (CrewAI Agent)  │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌───────┐ ┌────────┐
│ Code  │ │ Project│
│ Search│ │Structure│
└───┬───┘ └───┬────┘
    │         │
    └────┬────┘
         ▼
┌─────────────────┐
│ LLM Code Analysis│
│ Answer Questions│
└────────┬────────┘
         │
         ▼
    Analysis Results
```

### Context Caching
```python
# Codebase context cache
_user_project_context = {
    "chat_id_xxx": {
        "project_path": "myproject",
        "gitlab_url": "https://gitlab.example.com",
        "branch": "main",
        "timestamp": 1234567890,
    }
}

# 10-minute expiration
CONTEXT_EXPIRE_MINUTES = 10
```

## Context Storage

### Question Storage
```python
context_manager.add_message(
    chat_id=chat_id,
    content="Where is the user authentication logic implemented?",
    role="user",
)
```

### Answer Storage
```python
context_manager.add_message(
    chat_id=chat_id,
    content="According to code analysis...",
    role="assistant",
)
```

## Multi-turn Follow-up

```
User: @gemini /codebase myproject
Gemini: ✅ Codebase context set

User: @gemini Where is the project's database model defined?
Gemini: Database models are defined under the `src/models/` directory...

User: @gemini What fields does the User model have?
Gemini: According to `src/models/user.py`, the User model contains the following fields:
        - id: Integer, Primary Key
        - username: String(50)
        - email: String(100)
        ...

User: @gemini How can I modify it to add a phone number field?
Gemini: To add a phone number field, you need to modify the following files:
        1. `src/models/user.py` - Add phone_number field
        2. `migrations/` - Create database migration
        3. `src/schemas/user.py` - Update Pydantic Schema
        ...
```

## Key Decisions

| Decision Point | Current Solution | Alternatives |
|-------|---------|---------|
| Context Cache | 10 Minutes | Configurable |
| Code Indexing | Real-time fetch | Pre-indexing + Incremental updates |
| Cross-branch Query | Requires re-setting | Support temporary switching |
| Private Repo | GitLab Token | OAuth Authorization |

## To Be Considered

1. **Code Indexing**: Does a large repository require pre-indexing?
2. **RAG Integration**: Should a vector database be used to improve retrieval quality?
3. **Multi-repo Support**: Setting multiple codebase contexts simultaneously?
