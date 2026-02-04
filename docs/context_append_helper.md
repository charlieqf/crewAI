# Context Append Helper for File Outputs

## Why change
- Raw-context injection is duplicated in `aibot_callback.py` (auto-wrap path and <FILE> tag path). Divergence risks: inconsistent styling, missing context when upload fails, and harder maintenance.
- Regex-based insertion is scattered; harder to harden (e.g., ensure we append after the last real `</body>`/`</html>` and always escape raw context).
- Lack of a single entry point makes testing and future features (size limits, feature flags) painful.

## Goals
- Single helper to append escaped raw context to an HTML string, used by all file-output code paths.
- Consistent placement (use last `</body>` else `</html>` else append), consistent styling, and consistent escaping.
- Make it easy to add safeguards (max length, optional enable flag) and to unit-test.

## Proposed helper
- Location: `src/crewai_enterprise/utils/html_context.py` (or similar under `utils/`).
- API sketch:
  ```python
  def append_context_section(html: str, raw_context: str | None, *, max_len: int | None = None) -> str:
      """Escape and append raw_context to the end of html.
      - No-op if raw_context is falsy or html is empty.
      - Escapes with html.escape; wraps in <details> block.
      - Inserts before the last </body>; fallback to </html>; else appends.
      - If max_len is set and the escaped context exceeds it, truncate with marker.
      """
  ```
- Style: reuse the existing dark-block style; keep inline CSS to avoid external deps; centralized for future tweaks.

## Implementation steps
1) Add the helper module/function with escape + last-`</body>` insertion and optional truncation.
2) Replace both blocks in `aibot_callback.py` (auto-wrap fallback and <FILE> tag upload path) to call the helper. Ensure both local-save and upload use the same `final_content` from the helper.
3) Optional: add a small unit test for the helper (body present, only html present, no closing tags, and stray `</body>` inside <pre> to ensure we pick the last match).
4) Keep behavior otherwise identical (same wording/emoji), but centralized for future changes.

## Testing plan
- Manual: trigger `/file-html` in file_only_mode (no <FILE> output) and with explicit `<FILE>` output; verify context block appears once at the end and matches both local and cloud copies.
- Automated: unit tests for helper insertion/escaping/truncation.

## Challenges & Review Opinions (Antigravity's Critique)
- **Idempotency**: The helper should detect if a context section already exists (e.g., via a specific HTML ID) to avoid double-injection if called multiple times on the same content.
- **Robust Insertion**: Instead of simple Regex, use a "find last closing tag" logic (rfind) to avoid breaking if the user content contains `</body>` inside a `<pre>` block.
- **Truncation Logic**: `max_len` should be applied to the *raw text* before escaping to ensure HTML entities aren't cut in half.
- **Centralization**: Once the helper is ready, `report_generator.py` should be updated to use it instead of its internal Jinja-based injection to ensure 100% UI consistency.
- **Styling**: Consider making the theme (Dark/Light) or primary color a parameter to allow for future UI flexibility.

## Non-task /context prefix behavior
- Only messages that start with `/` are parsed for prefix commands.
- `/context:<window>` can be combined with other leading slash tokens; the last `/context` wins.
- All `/context:*` prefix tokens are removed before the prompt is sent, with no user-visible acknowledgement.
