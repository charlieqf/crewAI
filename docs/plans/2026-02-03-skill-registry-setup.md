# OpenCode Required Skills Registration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ensure the required OpenCode skills (`opencode-debug`, `opencode-task-ops`, `wecom-archive-ops`, `wecom-daily-ops`, `wecom-opencode-task-ops`, `deploy-verify`) live in the correct directory, are registered, and are discoverable by `opencode debug skill`.

**Architecture:** OpenCode discovers skills by scanning `.opencode/skill/**/SKILL.md` (singular) and `.claude/skills/**/SKILL.md`. We will place the required skills under `.opencode/skill/<name>/SKILL.md`, validate frontmatter, then verify discoverability using `opencode debug skill`.

**Tech Stack:** OpenCode CLI, filesystem layout, SKILL.md frontmatter.

---

### Task 1: Inventory required skills and existing locations

**Files:**
- None

**Step 1: List expected skill directories**

Run: `ls .opencode/skill`
Expected: directory list (may be missing required skills)

**Step 2: Locate skill files in worktree**

Run: `ls opencode_skills`
Expected: list of candidate skill folders

**Step 3: Verify each required skill has SKILL.md**

Run (repeat for each):
`ls opencode_skills/<skill-name>/SKILL.md`
Expected: file exists for all required skills

**Step 4: Commit**

No commit for inventory.

---

### Task 2: Copy required skills into OpenCode discovery path

**Files:**
- Create: `.opencode/skill/<skill-name>/SKILL.md` (copied from worktree)

**Step 1: Create target dirs**

Run:
`mkdir -p .opencode/skill/opencode-debug .opencode/skill/opencode-task-ops .opencode/skill/wecom-archive-ops .opencode/skill/wecom-daily-ops .opencode/skill/wecom-opencode-task-ops .opencode/skill/deploy-verify`

**Step 2: Copy files (skip existing)**

Run (repeat per skill):
`cp -n opencode_skills/<skill-name>/SKILL.md .opencode/skill/<skill-name>/SKILL.md`
Expected: files copied only when missing

**Step 3: Commit**

```bash
git add .opencode/skill/opencode-debug/SKILL.md \
  .opencode/skill/opencode-task-ops/SKILL.md \
  .opencode/skill/wecom-archive-ops/SKILL.md \
  .opencode/skill/wecom-daily-ops/SKILL.md \
  .opencode/skill/wecom-opencode-task-ops/SKILL.md \
  .opencode/skill/deploy-verify/SKILL.md
git commit -m "chore: register required opencode skills"
```

---

### Task 3: Validate frontmatter and skill names

**Files:**
- Modify (if needed): `.opencode/skill/<skill-name>/SKILL.md`

**Step 1: Check frontmatter name matches folder**

Run (repeat per skill):
`python - <<'PY'
from pathlib import Path
path = Path('.opencode/skill/deploy-verify/SKILL.md')
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
PY`
Expected: `name` equals folder name (e.g., deploy-verify)

**Step 2: Fix mismatches (if any)**

Edit `name:` in frontmatter to match folder

**Step 3: Commit**

```bash
git add .opencode/skill/*/SKILL.md
git commit -m "chore: align skill frontmatter names"
```

---

### Task 4: Verify discoverability via OpenCode CLI

**Files:**
- None

**Step 1: List skills**

Run: `opencode debug skill > /tmp/skills.json`

**Step 2: Verify required skills are present**

Run:
`python - <<'PY'
import json
with open('/tmp/skills.json','r',encoding='utf-8') as f:
    data = json.load(f)
required = {
  'opencode-debug','opencode-task-ops','wecom-archive-ops',
  'wecom-daily-ops','wecom-opencode-task-ops','deploy-verify'
}
found = {s.get('name') for s in data}
missing = sorted(required - found)
print('missing:', missing)
PY`

Expected: `missing: []`

**Step 3: No commit**

---

### Task 5: Document skill locations (optional)

**Files:**
- Modify: `company_docs/wecom_callback_deployment_guide.md`

**Step 1: Add a note**

- OpenCode skills should live under `.opencode/skill/<name>/SKILL.md`
- Required skills list for this project

**Step 2: Commit**

```bash
git add company_docs/wecom_callback_deployment_guide.md
git commit -m "docs: note required opencode skills location"
```
