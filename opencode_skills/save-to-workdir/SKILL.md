---
name: save-to-workdir
description: Ensure any claimed file output is written to disk in the task workdir before mentioning it.
---

# Save Files To Workdir

- When you say a file is saved, you must write it to disk in the current working directory first.
- Verify the file exists after writing (e.g., list or read it) before you claim it exists.
- Use the exact filename you mention (case-sensitive).
- Keep filenames safe: only [A-Za-z0-9._-].
- After writing, confirm by mentioning the relative path.
- At the start of your reply, add: "Using skill: save-to-workdir".
- Do not claim a file exists if you did not write it.
