# GitLab Code Review System - Architecture

This document outlines the architecture for an intelligent code review system using CrewAI and GitLab.

## 1. Overview

### Problem Statement
Traditional code review tools only show diffs, lacking deep context understanding. Reviewers must manually trace:
- How a changed function is called elsewhere
- What security implications a modification has
- Whether the change breaks existing patterns

### Solution
An AI-powered multi-agent system that:
1. **Understands context** - Reads full files, not just diffs
2. **Specializes** - Different agents focus on different concerns
3. **Integrates** - Works directly in WeCom for seamless workflow

## 2. System Architecture

```
┌─────────────────┐     ┌──────────────────────────────────────────┐
│   WeCom User    │     │              Kamatera Server             │
│                 │     │  ┌──────────────────────────────────────┐│
│  @gemini        │────▶│  │         aibot_callback.py            ││
│  review commit  │     │  │  ┌─────────────────────────────────┐ ││
│                 │     │  │  │       CodeReviewFlow            │ ││
└─────────────────┘     │  │  │  ┌───────────┐ ┌───────────┐   │ ││
                        │  │  │  │ Arch Agent│ │ Perf Agent│   │ ││
                        │  │  │  │  (Claude) │ │  (Gemini) │   │ ││
                        │  │  │  └─────┬─────┘ └─────┬─────┘   │ ││
                        │  │  │        └──────┬──────┘         │ ││
                        │  │  │         ┌─────▼─────┐          │ ││
                        │  │  │         │Summary Agt│          │ ││
                        │  │  │         │ (Gemini)  │          │ ││
                        │  │  │         └───────────┘          │ ││
                        │  │  └─────────────────────────────────┘ ││
                        │  └──────────────────────────────────────┘│
                        │                    │ VPN                 │
                        │                    ▼                     │
                        │         ┌──────────────────┐             │
                        │         │  GitLab Server   │             │
                        │         │  (Private)       │             │
                        │         └──────────────────┘             │
                        └──────────────────────────────────────────┘
```

## 3. Core Components

### 3.1 GitLabTool
**Purpose:** Interface with GitLab API via `python-gitlab` SDK.

| Action | Description |
|--------|-------------|
| `get_diff` | Get commit diff |
| `get_mr_changes` | Get MR changes |
| `get_file` | Read file content (with binary handling) |
| `search_code` | Search code in project |
| `list_files` | List directory structure |
| `post_comment` | Post review comment |

**Notes:**
- `get_file`, `list_files`, and `search_code` all support `ref` parameter for branch/commit targeting.

### 3.2 Specialized Agents

| Agent | Provider | Focus Area |
|-------|----------|------------|
| Architecture & Security | Claude | Design patterns, security vulnerabilities, coupling |
| Performance | Gemini | Algorithm complexity, N+1 queries, resource leaks |
| Testing | GPT-4 | Test coverage, error handling (currently disabled) |
| Summary | Gemini | Aggregates findings, resolves conflicts |

**Prompt Engineering:**
- All prompts in English for consistent reasoning
- Final output always in Chinese
- Explicitly instruct agents to use `ref` parameter

### 3.3 Orchestration Flows

#### CodeReviewFlow
```
Input: gitlab_url, project_id, commit_sha
  │
  ├─▶ Parallel Execution
  │   ├── Arch Agent reviews commit
  │   └── Perf Agent reviews commit
  │
  └─▶ Summary Agent aggregates → Final Report
```

#### CodebaseQAFlow
```
Input: gitlab_url, project_id, query, branch
  │
  └─▶ QA Agent searches, reads, and answers
```

### 3.4 WeCom Integration

**Trigger Conditions:**
1. **Code Review:** Message contains GitLab commit URL
2. **Codebase QA:** Previous project context exists + question detected
3. **Vision + Code:** Screenshot + project context triggers code search

**Project Context:**
- Stored in `_user_project_context` (chat_id → project_path)
- Set when user triggers a code review
- Persists for follow-up questions

## 4. Supported User Scenarios

| # | Scenario | Example Message | Implementation Status |
|---|----------|-----------------|----------------------|
| 1 | **Code Review** | `Review https://gitlab.example.com/.../commit/abc123` | ✅ Complete |
| 2 | **Set Codebase Context** | `/codebase https://gitlab.example.com/team/project` | ✅ Complete |
| 3 | **Feature Location** | `Where is the login function implemented?` | ✅ Complete |
| 4 | **Error Diagnosis** | `I'm getting 'KeyError: user_id', what's the cause?` | ✅ Complete |
| 5 | **Script Usage** | `How do I call abc.py? Give me CLI examples` | ✅ Complete |
| 6 | **Screenshot Diagnosis** | `[screenshot] What's causing this error?` | ✅ Complete |

### Scenario Details

#### 1. Code Review (Commit URL)
- **Trigger:** Message contains GitLab commit URL AND one of:
  - Positive keywords: `review`, `审查`, `审核`, `检查`, `看看`, `帮我看`
  - OR message is ONLY the URL (no other text)
- **Blocked by:** Negative keywords like `不要审查`, `别审查`, `don't review`
- **Flow:** `CodeReviewFlow` → Parallel agents → Summary
- **Side Effect:** Also sets project context for future Q&A
- **Output:** Comprehensive review report in Chinese

#### 2. Set Codebase Context (`/codebase` Command)
- **Trigger:** Message contains `/codebase`
- **Formats:**
  - `/codebase https://gitlab.example.com/team/project` (set context only)
  - `/codebase https://gitlab.example.com/team/project 登录功能在哪里？` (set + ask in one message)
  - `/codebase team/project`
- **Effect:** Sets project context; if question included, immediately triggers analysis
- **Output:** Confirmation message OR direct answer if question provided

#### 3-5. Codebase Q&A (Text Questions)
- **Prerequisite:** User must have triggered a code review first (to establish project context)
- **Context Source:** Project path cached from the last code review URL
- **Trigger:** Question keywords detected: `哪里`, `怎么`, `报错`, `error`, `exception`, `how to`, `where`
- **Flow:** `CodebaseQAFlow` → Single QA agent queries the cached project
- **Branch:** Defaults to `main` (future: allow specifying branch)
- **Output:** Answer with file references in Chinese

#### 6. Screenshot + Code Analysis
- **Prerequisite:** User must have triggered a code review first
- **Trigger:** Image message sent while project context exists
- **Flow:** Vision LLM analyzes image → `CodebaseQAFlow` uses image description to search code
- **Output:** Combined vision + code analysis in Chinese

### How Project Context Works

```
User: "Review https://gitlab.example.com/team/myproject/-/commit/abc123"
        │
        └──▶ System caches: chat_id → "team/myproject"
        
(Later in the same chat)

User: "Where is the login function?"
        │
        └──▶ System detects question + finds cached "team/myproject"
        └──▶ Triggers CodebaseQAFlow with project="team/myproject"
```

> **Note:** If no code review has been triggered in the chat, scenarios 2-5 will NOT activate and the message will be handled by the regular LLM.

## 5. Data Flow

### Code Review Flow
1. User sends: `@gemini review https://gitlab.example.com/.../commit/abc123`
2. `aibot_callback.py` detects GitLab URL via regex
3. Extracts: project_path, commit_sha
4. Creates `CodeReviewFlow` instance
5. Flow runs agents in parallel
6. Summary agent produces final report
7. Bot sends report back to user

### Codebase QA Flow
1. User sends: `Where is the login function implemented?`
2. System detects code-related question + active project context
3. Creates `CodebaseQAFlow` instance
4. Agent searches and reads code
5. Bot responds with answer including file references

## 6. Configuration

### Environment Variables
```bash
GITLAB_URL=https://gitlab.example.com
GITLAB_TOKEN=<personal_access_token>

OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
GEMINI_API_KEY=...
```

### Network Requirements
- Server must have VPN access to GitLab if private
- GitLab token needs `read_api` and `read_repository` scopes

## 7. Security Considerations

1. **Token Storage:** GitLab token stored in `.env`, never in code
2. **Access Control:** Bot only accesses projects the token has access to
3. **Input Sanitization:** File paths sanitized before API calls
4. **Binary Handling:** Non-UTF-8 files return placeholder, not raw bytes

## 8. Future Enhancements

- [ ] MR-level review (not just commits)
- [ ] Auto-post comments to GitLab
- [ ] Re-enable Testing Agent with better prompts
- [ ] Support multiple GitLab instances per user
- [ ] Persistent project context (Redis)
