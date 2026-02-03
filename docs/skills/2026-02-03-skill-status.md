# OpenCode Skills Status (2026-02-03)

## Required Skills

- opencode-debug
- opencode-task-ops
- wecom-archive-ops
- wecom-daily-ops
- wecom-opencode-task-ops
- deploy-verify

## Where They Live (Worktree)

All required skills are in the worktree discovery path:

- `C:\work\code\crewAI\.worktrees\opencode-task-context\.opencode\skill\opencode-debug\SKILL.md`
- `C:\work\code\crewAI\.worktrees\opencode-task-context\.opencode\skill\opencode-task-ops\SKILL.md`
- `C:\work\code\crewAI\.worktrees\opencode-task-context\.opencode\skill\wecom-archive-ops\SKILL.md`
- `C:\work\code\crewAI\.worktrees\opencode-task-context\.opencode\skill\wecom-daily-ops\SKILL.md`
- `C:\work\code\crewAI\.worktrees\opencode-task-context\.opencode\skill\wecom-opencode-task-ops\SKILL.md`
- `C:\work\code\crewAI\.worktrees\opencode-task-context\.opencode\skill\deploy-verify\SKILL.md`

OpenCode discovers skills from `.opencode/skill/**/SKILL.md` in the current repo/worktree.

## Current Discovery Status

OpenCode CLI can see the skills from the worktree (verified via `opencode debug skill`).

The Skill tool in this session still misses:
- `wecom-daily-ops`
- `deploy-verify`

This suggests the Skill tool is bound to a different working directory or needs a session refresh.

## What To Do Next

1) Restart OpenCode from the worktree root:
   - `C:\work\code\crewAI\.worktrees\opencode-task-context`

2) Re-run:
   - `opencode debug skill`
   - Load skills again with the Skill tool

3) If the Skill tool still cannot load them, copy these same folders to the main repo path:
   - `C:\work\code\crewAI\.opencode\skill\<name>\SKILL.md`

That makes the skills available even when the session is not launched from the worktree.
