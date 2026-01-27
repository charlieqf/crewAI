# WeCom AI Assistant Interaction Guide (OpenCode + OMO)

This guide provides a detailed list of chat patterns, commands, and automated interaction methods available for the AI Assistant (powered by OpenCode and OhMyOpenCode) within the WeCom environment.

## 1. Triggers and Basic Conversation

To balance convenience with group chat signal-to-noise ratios, the following trigger logic is applied:

| Scenario | Trigger Method | Description |
|------|----------|------|
| **Private Chat (1:1)** | Send message directly | The AI Assistant responds to every message, similar to a standard chat. |
| **Group Chat** | **Must @Mention the bot** | Follows the standard ChatGPT/Gemini/Grok bot pattern. The bot does not listen to irrelevant messages and only triggers when explicitly mentioned. |
| **All Scenarios** | **Slash Commands (/)** | Any message starting with `/` will trigger the corresponding function regardless of @mentions. |

> [!TIP]
> **Context Awareness**: Even if you @mention the bot only once in a group chat, it will automatically retrieve the recent conversation background (such as code snippets or discussion logs) via the integrated **Conversation Archive** service to ensure coherent and contextual responses.

### OpenCode Native Sync Policy
When `@OpenCode` is enabled, the bridge continuously syncs messages into OpenCode using `noReply: true`.
This makes OpenCode feel like a resident teammate without triggering LLM calls.

- **Always-on sync**: Every message in monitored chats is synced silently.
- **Context Awareness**: Context is per‑chat; no memory across different chats in Phase 1.
- **Compaction**: OpenCode handles context trimming via its native SessionCompaction.
- **Privacy note**: This is a behavior change vs. mention-only bots. All messages are captured for the OpenCode session.
- **Bot message filtering**: Messages from other AI bots are not synced by default to avoid polluting context.
  - Users can explicitly quote a bot message to include it if needed.
- **Files/images**:
  - Always include metadata (filename, type, storage key).
  - Include extracted text only if small; otherwise include a short summary or pointer.

### Default Assistant: Sisyphus
When you trigger a conversation without specifying a particular sub-agent, the default assistant is **Sisyphus**—a powerful multi-agent orchestrator.
- **Example (Group)**: `@OpenCode please analyze this bug.`
- **Experience**: Sisyphus will decompose the task and may call upon specialized sub-agents for collaboration.

---

## 2. Task Lifecycle (OMO-Aligned)

OpenCode + OMO already defines a full task lifecycle. The WeCom bridge should map chat interactions to these phases:

### A) Quick Work (ulw / ultrawork)
- **Trigger**: Include `ulw` or `ultrawork` in the message.
- **Behavior**: Sisyphus explores, delegates, implements, and verifies without a formal plan.
- **Use When**: Small-to-medium tasks where speed matters more than formal planning.

### B) Planned Work (@Plan -> /start-work)
- **Trigger**: Use `@Plan` (Prometheus) or `/plan` to begin an interview-driven plan.
- **Plan Artifact**: Prometheus writes a plan in `.sisyphus/plans/*.md`.
- **Execution**: `/start-work` executes the plan via Atlas (orchestrator) with delegated subagents.
- **Use When**: Multi-step, high-risk, or long-running work where clarity and verification matter.

### C) Execution, Verification, Handoff
- **Execution**: Atlas delegates tasks to specialized agents and tracks TODOs.
- **Verification**: LSP diagnostics and tests are run before completion.
- **Handoff**: The assistant posts a final summary, risks, and next actions for humans.

### D) Continuity (Resume / Cancel)
- **Resume**: `/start-work` continues from `boulder.json` if a session was interrupted.
- **Cancel**: `/cancel-ralph` stops loops; `/stop` (bridge-level) halts active work.

> [!NOTE]
> Prometheus and Atlas are designed to work as a pair. For complex tasks, prefer `@Plan` then `/start-work`.

---

## 3. Specialized Sub-Agents (@Agent)

If you have a task that requires a specific domain expert, you can trigger a specialized sub-agent directly by using their handle.

- **Single-bot convention**: Use `@OpenCode @Agent` in the same message.  
  The bridge routes the agent tag to OpenCode without requiring separate WeCom bots.
  - Example: `@OpenCode @Oracle review the auth design`

- **@Oracle**: Focuses on deep architecture design, complex logic refactoring, and security analysis.
  - *Example*: "@Oracle help me design a session management system for high-concurrency."
- **@Librarian**: Focuses on documentation lookup, best practice searches, and cross-repo references.
  - *Example*: "@Librarian find the best practices for handling SSE streams in FastAPI."
- **@Explore**: Focuses on pattern recognition and relational search across large codebases.
  - *Example*: "@Explore find all instances where the `v1/legacy/auth` endpoint is used."
- **@Plan**: Prometheus (planner) interviews, clarifies scope, and writes a plan.
  - *Example*: "@Plan design a migration plan for the auth service."
- **@Frontend**: UI/UX expert for visual changes and product polish.
  - *Example*: "@Frontend refresh the login page in a fintech style."

---

## 4. Command System (WeCom + OMO)

### 4.1 Syntax and Rules
- **Prefix**: Commands start with `/` and must be the first token in the message.
- **Arguments**: Use quotes for multi-word inputs. Example: `/plan "Refactor auth service"`.
- **Scope**: Commands are scoped to the current chat. Session state is tracked by `chat_id + user_id`.
- **Ownership**: The user who starts a task can cancel it. Admins can override if needed.
- **Precedence**: Slash commands override normal prompt handling.

### 4.2 Commands (Forwarded to OpenCode / OMO)

| Command | Description | Use Case |
|------|----------|----------|
| `/plan "<goal>"` | Start Prometheus interview and plan generation | Large or risky tasks |
| `/start-work [plan-name]` | Execute the latest plan | Implement planned work |
| `/refactor <target>` | Refactor with LSP/AST support | Structured refactors |
| `/ralph-loop "<goal>"` | Continuous work loop until completion | Self-correcting iterations |
| `/ulw-loop "<goal>"` | Ralph loop + ultrawork mode | Maximum depth tasks |
| `/cancel-ralph` | Cancel active loop | Stop continuous runs |
| `/init-deep` | Generate AGENTS.md hierarchy | New codebase onboarding |

### 4.3 Bridge-Level Commands (WeCom UX)

These are handled by the WeCom bridge for team coordination.

| Command | Description | Use Case |
|------|----------|----------|
| `/status` | Show active task, phase, and last update | Quick check-in |
| `/resume` | Resume the most recent task | After a pause |
| `/stop` | Stop current task execution | Emergency halt |
| `/handoff @user` | Assign next step to a human | Human decision or review |
| `/reset` | Start a new OpenCode session for the chat | Clean slate |

---

## 5. Team Workflow Scenarios (AI Colleagues + Humans)

This section models common "dev team" interactions with AI colleagues.

### 5.1 Bug Triage -> Fix -> Verify
```
User: @OpenCode We have 500 errors on /api/payments since the last deploy.
Sisyphus: I will investigate. Do you have a recent stack trace or logs?
User: [shares logs]
Sisyphus: I will analyze logs and search code. I will ask @OpenCode @Oracle for root-cause review.
Oracle: Likely null access in payments handler when currency is missing.
Sisyphus: Proposed fix in payments handler. Run tests? (yes/no)
User: yes
Sisyphus: Tests passed. Patch ready. Do you want me to proceed?
```

### 5.2 Feature Request -> Plan -> Execute
```
User: @OpenCode We need OAuth login for the mobile app.
Sisyphus: This is multi-step. I suggest a plan. Use /plan?
User: /plan "Add OAuth login for mobile app"
Prometheus: (interview questions)
User: (answers)
Prometheus: Plan saved. Run /start-work to execute.
User: /start-work
Sisyphus: Executing plan. Status updates will follow.
```

### 5.3 Architecture Decision Review
```
User: @OpenCode @Oracle Should we use Redis or Postgres for session storage?
Oracle: Tradeoffs, risks, and recommendation...
User: @OpenCode summarize Oracle's recommendation and next steps.
```

### 5.4 Codebase Exploration / Docs Lookup
```
User: @OpenCode @Explore Find where the billing webhook is validated.
Explore: Found handlers in src/billing/webhooks.py and middleware/auth.py
User: @OpenCode @Librarian Find official Stripe guidance on webhook retries.
Librarian: Summary + link references (high level)
```

### 5.5 UI / Frontend Collaboration
```
User: @OpenCode @Frontend redesign the login screen to match a fintech style.
Frontend: Proposed layout, palette, and component changes.
User: @OpenCode apply the change and show me the diff.
```

### 5.6 Refactor With Guardrails
```
User: /refactor src/auth --scope=module --strategy=safe
Sisyphus: Running refactor with LSP/AST tools. I will report changes and tests.
```

### 5.7 Incident Response / Hotfix
```
User: @OpenCode Production is down. ultrawork investigate and propose a fix.
Sisyphus: I will investigate immediately and post findings with a rollback option.
```

### 5.8 Handoff and Human Approval
```
Sisyphus: I can proceed with the DB migration now. Approve? (yes/no)
User: yes
Sisyphus: Proceeding.
```

### 5.9 Code Review / PR Review
```
User: @OpenCode Review PR #123 and flag high-risk changes.
Sisyphus: Summary + critical risks + tests to run before merge.
```

### 5.10 CI Failure / Test Triage
```
User: @OpenCode CI failed on main. Investigate.
Sisyphus: Failing tests, likely root cause, proposed fix.
```

### 5.11 Dependency Upgrade / Security Patch
```
User: @OpenCode Upgrade OpenSSL and check breaking changes.
Sisyphus: Impact analysis + mitigation steps + verification plan.
```

### 5.12 Release Notes / Stakeholder Update
```
User: @OpenCode Draft release notes for v1.4.
Sisyphus: Highlights, breaking changes, risks, rollout notes.
```

### 5.13 Data Migration / Schema Change
```
User: @OpenCode @Plan Migrate user table to UUIDs.
Prometheus: Plan + rollback + validation steps.
```

### 5.14 Performance Regression
```
User: @OpenCode Latency increased 2x after deploy.
Sisyphus: Profiling plan + likely hot spots + optimization options.
```

### 5.15 Onboarding / Handover
```
User: @OpenCode Summarize this repo for new devs.
Sisyphus: Key services, entry points, run steps, owners.
```

### 5.16 Security / Risk Review
```
User: @OpenCode @Oracle Do a quick security review of the auth flow.
Oracle: Threats + mitigations + areas needing human review.
```

### 5.17 Hard or Impossible Scenarios (Explicit Limits)
The assistant cannot reliably handle these without extra access or human input:

- **Zero-error guarantees**: AI cannot guarantee correctness or absence of bugs in all cases.
- **No-credential access**: Private repos, prod logs, or internal dashboards require credentials.
- **Offline artifacts**: Messages or files not in WeCom/archive storage cannot be reconstructed.
- **GUI-only workflows**: Actions that require a human GUI click path (no API/automation).
- **Policy/approval bypass**: AI cannot override legal/compliance approvals or security policies.
- **Cross-org access**: Data from other teams or chats is unavailable unless explicitly shared.

---

## 6. Tasks and Automated Feedback

### TODO Management
The AI Assistant proactively creates TODOs during complex tasks, and you can participate in managing them.
- **Example**: "List current TODO progress."
- **Example**: "Add 'Write unit tests' to the TODO list."

### Real-time Status Updates
During task execution, the system provides real-time feedback via status messages:
- "Oracle is analyzing interface compatibility..."
- "Librarian is retrieving official documentation..."
- "Running `lsp_diagnostics` to verify the fix..."

---

## 7. Advanced Interaction Features

### Guided Clarification
When an instruction is ambiguous, the AI will proactively offer options:
- **AI Response**: "I'm not sure if you mean refactoring the existing module or creating a new one. I suggest Option A: [Description] or Option B: [Description]. Which do you prefer?"

### Human Handoff
When a decision is required or risk is high, the assistant will request approval or delegate to a human.
- **Example**: "This change affects auth and billing. Please confirm before I proceed."

### Vision Support
If your WeCom setup allows sending images, the AI can analyze UI errors or architectural diagrams.
- **Action**: Send a console error screenshot + "Help me fix this error."
- **Experience**: The AI uses its vision capabilities to locate the specific line of code.

---

## 8. Pro-tips for Better Interaction
- **Detail over Brevity**: Providing stack traces or expected behavior helps Sisyphus locate bugs much faster.
- **Session Continuity**: The AI remembers the context within a specific chat. To start fresh, simply say "Start a new task."
