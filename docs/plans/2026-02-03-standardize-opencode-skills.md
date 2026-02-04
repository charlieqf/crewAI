# Standardize OpenCode Skills Configuration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Standardize skill storage to the OpenCode‑documented locations so skills are consistently discoverable across worktrees and sessions.

**Architecture:** Use `.opencode/skills/<name>/SKILL.md` for project/worktree skills and optionally `~/.config/opencode/skills/<name>/SKILL.md` for global skills. Remove deprecated locations (`.opencode/skill`, `opencode_skills`). Validate frontmatter name compliance and verify discovery via `opencode debug skill`.

**Tech Stack:** OpenCode CLI, filesystem layout, SKILL.md frontmatter.

---

### Task 1: Inventory current skill locations

**Files:**
- None

**Step 1: List current project skill folders**

Run (from worktree root):
`dir .opencode`

Expected: identify whether `.opencode/skills` and/or `.opencode/skill` exist.

**Step 2: List current skills under each location**

Run:
`dir .opencode\skills`
`dir .opencode\skill`

Expected: see which skills live under each path.

**Step 3: No commit**

---

### Task 2: Move skills to the correct project path

**Files:**
- Create/Move: `.opencode/skills/<name>/SKILL.md`
- Delete: `.opencode/skill/<name>/SKILL.md` (after move)

**Step 1: Create target directories**

Run (repeat per required skill):
`mkdir .opencode\skills\opencode-debug`
`mkdir .opencode\skills\opencode-task-ops`
`mkdir .opencode\skills\wecom-archive-ops`
`mkdir .opencode\skills\wecom-daily-ops`
`mkdir .opencode\skills\wecom-opencode-task-ops`
`mkdir .opencode\skills\deploy-verify`

**Step 2: Move SKILL.md files**

Run (repeat per skill):
`move .opencode\skill\<name>\SKILL.md .opencode\skills\<name>\SKILL.md`

**Step 3: Remove old `.opencode/skill` directory**

Run:
`rmdir /s /q .opencode\skill`

**Step 4: Commit**

```bash
git add .opencode/skills
git rm -r .opencode/skill
git commit -m "chore: standardize opencode skills path"
```

---

### Task 3: Validate frontmatter names

**Files:**
- Modify (if needed): `.opencode/skills/<name>/SKILL.md`

**Step 1: Check frontmatter**

Run (repeat per skill):
```bash
python - <<'PY'
from pathlib import Path
path = Path('.opencode/skills/deploy-verify/SKILL.md')
text = path.read_text(encoding='utf-8')
if not text.startswith('---'):
    raise SystemExit('missing frontmatter')
name = None
for line in text.splitlines():
    if line.strip() == '---' and name:
        break
    if line.strip().startswith('name:'):
        name = line.split(':',1)[1].strip()
print('name:', name)
PY
```

Expected: `name` equals folder name.

**Step 2: Fix mismatches**

Edit the `name:` field to match the folder.

**Step 3: Commit**

```bash
git add .opencode/skills/*/SKILL.md
git commit -m "chore: align skill frontmatter names"
```

---

### Task 4: Verify discovery

**Files:**
- None

**Step 1: List skills**

Run:
`opencode debug skill > .opencode/skills.json`

**Step 2: Verify required skills present**

```bash
python - <<'PY'
import json
with open('.opencode/skills.json','r',encoding='utf-8') as f:
    data = json.load(f)
required = {
  'opencode-debug','opencode-task-ops','wecom-archive-ops',
  'wecom-daily-ops','wecom-opencode-task-ops','deploy-verify'
}
found = {s.get('name') for s in data}
missing = sorted(required - found)
print('missing:', missing)
PY
```

Expected: `missing: []`

**Step 3: No commit**

---

### Task 5: (Optional) Configure global skills

**Files:**
- Create (optional): `%USERPROFILE%\.config\opencode\skills\<name>\SKILL.md`

**Step 1: Create global directory**

Run:
`mkdir %USERPROFILE%\.config\opencode\skills`

**Step 2: Copy skills (if you want global availability)**

Run (repeat per skill):
`xcopy /e /i .opencode\skills\<name> %USERPROFILE%\.config\opencode\skills\<name>`

**Step 3: No commit**
