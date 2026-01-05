# GitLab Code Review System - Implementation Walkthrough

This document details the implementation of the intelligent multi-agent code review system.

## 1. Components Implemented

### A. Enhanced GitLabTool
**File:** `src/crewai_enterprise/tools/gitlab/gitlab_tool.py`

Updated to use `python-gitlab` SDK with the following capabilities:
- `get_file`: Retrieve full file content with proper binary/UTF-8 handling.
- `search_code`: Search for code snippets with lazy iteration (max 10 results).
- `list_files`: List directory structure.
- `get_diff`, `get_mr_changes`, `post_comment`: Standard GitLab operations.

**Key Features:**
- Supports `ref` parameter for all file operations (branch/commit SHA).
- Handles non-UTF-8/binary files gracefully.

### B. Specialized Review Agents
**File:** `src/crewai_enterprise/agents/code_review_agents.py`

| Agent | LLM | Focus |
|-------|-----|-------|
| Architecture & Security | Claude | Design patterns, security risks |
| Performance | Gemini | Algorithm complexity, resource usage |
| Testing (Disabled) | GPT-4 | Test coverage, maintainability |
| Summary | Gemini | Aggregates findings into final report |

### C. Codebase QA Agent
**File:** `src/crewai_enterprise/agents/codebase_qa_agents.py`

General-purpose agent for answering codebase questions:
- Feature location
- Error diagnosis
- Script usage
- Screenshot-based issue analysis

### D. Orchestration Flows
**Files:**
- `src/crewai_enterprise/flows/code_review_flow.py` - Code review workflow
- `src/crewai_enterprise/flows/codebase_qa_flow.py` - Q&A workflow

**CodeReviewFlow:**
1. Initializes `GitLabTool`.
2. Runs Architecture and Performance agents in **parallel**.
3. Summary Agent aggregates findings.
4. Returns final markdown report.

**CodebaseQAFlow:**
1. Takes user query and optional branch parameter.
2. Agent searches, reads, and analyzes code.
3. Returns evidence-based answer in Chinese.

### E. WeCom Integration
**File:** `src/crewai_enterprise/server/aibot_callback.py`

**Features:**
- **GitLab URL Detection**: Regex matches `https://<any-domain>/<path>/-/commit/<sha>`.
- **Project Context Caching**: Remembers last reviewed project for follow-up questions.
- **Code Review Trigger**: Detects commit URLs and triggers `CodeReviewFlow`.
- **Codebase QA Trigger**: Detects code-related questions and triggers `CodebaseQAFlow`.
- **Vision + Code**: Screenshot analysis can trigger code search if project context exists.

## 2. Configuration

Set these environment variables in `.env`:

```bash
# GitLab Integration
GITLAB_URL=https://gitlab.example.com
GITLAB_TOKEN=your_personal_access_token

# LLM Providers
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
GEMINI_API_KEY=...
```

## 3. Testing

### Unit Tests
```bash
python -m unittest tests/tools/test_gitlab_tool.py
```

### End-to-End Test
1. Start server:
   ```bash
   uvicorn src.crewai_enterprise.server.aibot_callback:app --reload
   ```
2. Send message to bot:
   ```
   Review this commit: https://gitlab.example.com/group/project/-/commit/abc123
   ```
3. Bot responds with multi-agent review report.

## 4. Dependencies

- `python-gitlab>=4.0.0` (added to `requirements-server.txt`)
