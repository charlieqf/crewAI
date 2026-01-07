# Distinguishing LLM Conversations vs Agent Tasks

## Core Differences

| Dimension | **LLM Conversation (Chat)** | **Agent Task (Task)** |
|-----|-------------------|---------------------|
| **Essence** | **Reactive**: One-question, one-answer, generates response based on context | **Goal-oriented**: Automatically plans and executes a series of steps to achieve a goal |
| **Execution Flow** | Linear: User Input -> LLM Processing -> Reply | Cyclic/Complex: Think -> *Call Tool* -> *Observe Result* -> Re-think -> Reply |
| **Time Consumption** | Short (seconds) | Long (possibly tens of seconds to minutes) |
| **Side Effects** | None (only generates text/files) | Yes (possibly modifies code, submits PRs, queries DBs, sends notifications) |
| **Boundaries** | Limited by context window and pre-trained knowledge | Can extend infinitely via tools (web search, DB query, code execution) |

---

## Agent Trigger Policy

How and when are Agents activated?

| Action | Mode | Trigger Rule |
| :--- | :--- | :--- |
| **Code Review** | **Autonomous** | Detects a GitLab commit URL. Triggers if URL only or URL + keywords (review, 审查, etc.). |
| **Bug Fix** | **Manual** | Requires explicit command: `/fix_bug` + @mention. |
| **Daily Report** | **Scheduled** | Crontab at 18:00 daily + manually via `@bot /report`. |
| **Project Scaffolding** | **Manual** | Requires explicit command: `/new_project`. |
| **Codebase QA** | **Direct LLM** | Activated via `/codebase`. (Not a full Agent, but tool-assisted). |

---

## Scenario Classification Matrix

### 1. Pure LLM Conversation (Direct Chat)
- **Basic Conversation**: "What is yield in Python?"
- **Custom Persona**: "You are a product manager..." (/set_prompt)
- **File & Image Analysis**: "Summarize this PDF"

### 2. Enhanced LLM Conversation (RAG/Tool-assisted Chat)
- **Codebase QA (/codebase)**:
    - *Mechanism*: Detect context -> Retrieve relevant code snippets -> Inject into Context -> LLM Answer.
- **Historical Recall**:
    - "What was said last Friday?" -> Retrieve Archive DB -> Summarize Answer.

### 3. CrewAI Agent Task (Autonomous Agents)
- **Code Review**:
    - *Policy*: **Passive Monitoring**. The system scans all messages for specific patterns (GitLab URLs).
- **Complex Bug Fix**:
    - *Policy*: **Active Activation**. User must explicitly request a fix.

---

## Architectural Mapping

### Path A: FastAPI -> `_call_llm_async`
**(Used for LLM Conversation & Enhanced Conversation)**
- **Lightweight**, direct streaming return.

### Path B: FastAPI -> `CrewAI Flow` / `Agent`
**(Used for Agent Tasks)**
- **Heavyweight**, often asynchronous via Background Task.

---

## Decision Guide: When to use an Agent?

1. **Does it need multi-step reasoning?** -> **Agent**
2. **Does it need external writing tools?** (Submit code, send emails) -> **Agent**
3. **Does it need multi-role perspectives?** (Both security audit and performance evaluation) -> **CrewAI**
4. **Is it a long-running, non-blocking task?** -> **Agent**

If it's just "answering questions based on context," **keeping it in the LLM conversation layer** is faster.
