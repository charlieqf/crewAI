# Critical Review & Risk Audit: WeCom-OpenCode Integration

This document outlines potential flaws, risks, and architectural challenges in the current [opencode_integration_plan.md](file:///c:/work/code/crewAI/company_docs/opencode_integration_plan.md).

## 1. The "Context Overload" Risk (SOLVED)
**Resolution**: The discovery of the `noReply: true` flag in OpenCode's API allows for **Native Sync**. 
- **Solution**: Every message is synced silenty into OpenCode's internal session history. 
- **Benefit**: When a mention occurs, the context is already "resident" in OpenCode. We no longer need to pull and inject a massive 50k char window on every trigger, significantly reducing latency and Bridge complexity.
- **Compaction**: OpenCode internally handles `SessionCompaction`, ensuring the context window stays healthy without Bridge intervention.

## 2. Stateless Bridge vs. Stateful OpenCode
**Challenge**: WeCom is a series of stateless HTTP callbacks. OpenCode relies on persistent process state.
- **Problem**: If the bridge service restarts, we must ensure the `WeCom_ChatID -> OpenCode_SessionID` mapping is persisted in a database (e.g., Redis or SQLite). Currently, the plan assumes memory-only mapping.
- **Mitigation**: Explicitly define a **Persisted Session Store** in the bridge architecture.

## 3. Concurrency & Locking
**Challenge**: How does the system handle "cross-talk"?
- **Problem**: In a group chat, User A mentions `@OpenCode` while User B is already running a `/ralph-loop`. OpenCode instances are usually tied to a single workspace directory (`Cwd`). 
- **Risk**: Concurrent file writes by two different subagents on the same branch/directory will lead to corruption or race conditions.
- **Refinement**: Implement a **Per-Chat Request Queue**. Only one active OMO task can hold the "Workspace Lock" at a time.

## 4. The "Feedback Spam" Problem
**Challenge**: Real-time status updates via SSE.
- **Problem**: OMO's subagents (Oracle, Explorer, Librarian) generate *a lot* of internal thoughts. Sending a WeCom message for every "Librarian is searching..." event will overwhelm the group.
- **Refinement**: **Throttle & Batching**. The bridge should only update the status every 10-15 seconds or only on "Major Phase Shifts" (e.g., Planning -> Executing -> Verifying).

## 5. Security & Destructive Actions
**Challenge**: Full "build" access in a group chat.
- **Problem**: Anyone in the group could theoretically say `@OpenCode rm -rf /`. 
- **Critical Requirement**: We need a **Human-in-the-Loop (HITL)** gateway for certain tool uses (bash, writing to sensitive files, git push). The bridge should send a clickable "Approve/Reject" card for risky actions.

## 6. OMO Lifecycle Mapping Gaps
**Challenge**: Interaction between Bridge and OMO's "Interview" mode.
- **Problem**: When `@Plan` (Prometheus) asks a clarification question, WeCom's 5s callback window will have long closed. 
- **Execution**: The bridge needs to handle "Awaiting Input" states, where it recognizes the next message from the user as an answer to the AI's question, not a new prompt.
