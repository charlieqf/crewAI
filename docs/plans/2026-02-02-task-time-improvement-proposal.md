# Task Time Improvement Proposal

## Goal
Reduce end-to-end task completion time (not just earlier partial output) by avoiding replays/timeouts and ending turns once a stable final answer is available.

## Current Bottlenecks
- Task worker uses blocking `prompt_interactive`, which can timeout and trigger replay.
- Completion waits for the full agent loop even after a stable response exists.

## Proposed Changes (High Gain, Low Risk)
1) Switch task worker to polling (`prompt_interactive_with_polling`).
2) Task-only timeout tuning: shorter `response_stable_timeout`, conservative `max_wait`.
3) Optional: use a faster model for tasks only if needed.

## Expected Impact
- Avoids replay-driven delays (minutes saved).
- Shorter average completion time by stopping on stable response.
- No UI changes required.

## Implementation Plan (If Approved)
### Task 1: Task Worker Polling
- Modify: `src/crewai_enterprise/server/task_worker.py`
- Replace `prompt_interactive` with `prompt_interactive_with_polling`

### Task 2: Task-Only Timeout Tuning
- Modify: `src/crewai_enterprise/server/opencode_client.py`
- Add task-specific timeout settings (env or parameters)

### Task 3: Verification
- Compare time to first and final response, and replay count.

### Task 4: Ops Docs
- Update `ops/daily_ops_runbook.md` with new behavior and tuning knobs.
