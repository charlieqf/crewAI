# Global OpenCode Skills Setup Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the full shared skill library available in every worktree session by installing it in the global OpenCode skills directory, while keeping the 6 project‑specific skills in the worktree.

**Architecture:** OpenCode loads skills from both project (`.opencode/skills/<name>/SKILL.md`) and global (`%USERPROFILE%\.config\opencode\skills/<name>/SKILL.md`) locations. We will copy the main repo’s skill library into the global directory and leave the worktree’s 6 skills intact.

**Tech Stack:** OpenCode CLI, Windows filesystem, SKILL.md frontmatter.

---

### Task 1: Create global skills directory

**Files:**
- Create: `C:\Users\rdpuser\.config\opencode\skills\`

**Step 1: Create directory**

Run:
`mkdir C:\Users\rdpuser\.config\opencode\skills`

**Step 2: Verify directory exists**

Run:
`dir C:\Users\rdpuser\.config\opencode\skills`

Expected: empty directory listing.

**Step 3: Commit**

No commit (global dir is outside git).

---

### Task 2: Populate global skills from main repo

**Files:**
- Create: `C:\Users\rdpuser\.config\opencode\skills\<name>\SKILL.md`

**Step 1: Copy the full skill library**

Run:
`xcopy /e /i /y C:\work\code\crewAI\.opencode\skills C:\Users\rdpuser\.config\opencode\skills`

Expected: all skill folders copied.

**Step 2: Spot‑check a few skills**

Run:
`dir C:\Users\rdpuser\.config\opencode\skills\opencode-task-ops`
`dir C:\Users\rdpuser\.config\opencode\skills\wecom-archive-ops`

Expected: SKILL.md present.

**Step 3: Commit**

No commit (global path is outside git).

---

### Task 3: Verify skill discovery from worktree session

**Files:**
- None

**Step 1: Start OpenCode from worktree**

Run:
`cd C:\work\code\crewAI\.worktrees\opencode-task-context`

**Step 2: List skills**

Run:
`opencode debug skill > .opencode/skills.json`

**Step 3: Verify both local + global skills are present**

```bash
python - <<'PY'
import json
with open('.opencode/skills.json','r',encoding='utf-8') as f:
    data = json.load(f)
names = {s.get('name') for s in data}
required = {
  'opencode-debug','opencode-task-ops','wecom-archive-ops',
  'wecom-daily-ops','wecom-opencode-task-ops','deploy-verify'
}
print('missing local required:', sorted(required - names))
print('sample global exists:', 'typescript-expert' in names)
PY
```

Expected:
- `missing local required: []`
- `sample global exists: True`

**Step 4: Cleanup**

Run:
`del .opencode\skills.json`

**Step 5: Commit**

No commit.
