# Branch Workflow (Main vs Plan)

This repo uses two branches for planning and implementation:

## Branches

### `feat-wecom` (Main development)
- Purpose: implementation and operational fixes.
- Contains code changes, scripts, and updated docs.
- Use this branch for building and shipping features.

### `plan/wecom-task-link` (Planning)
- Purpose: implementation plan for the WeCom /task feature.
- Contains the plan doc only:
  - `docs/plans/2026-01-30-wecom-task-link.md`
- No code changes should be made here.

## How to use them

### 1) Review the plan

```bash
git fetch origin
git checkout plan/wecom-task-link
```

Read:
- `docs/plans/2026-01-30-wecom-task-link.md`

### 2) Implement the plan

```bash
git checkout feat-wecom
```

Then follow the plan tasks in order. Do not implement on the plan branch.

### 3) Keep plan and implementation separate

- Plan updates: commit only on `plan/wecom-task-link`.
- Code changes: commit only on `feat-wecom` (or a new feature branch if desired).

## Worktrees (if used)

If you use git worktrees, you may see two working directories:
- main worktree: `C:\work\code\crewAI`
- plan worktree: `C:\work\code\crewAI\.worktrees\wecom-task-plan`

This is still one repo; each worktree is just a separate working directory for a branch.
