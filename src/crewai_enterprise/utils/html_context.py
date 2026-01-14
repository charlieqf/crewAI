"""
Utilities for appending raw context blocks to generated HTML.

Centralizes styling, escaping, and placement so file outputs and reports
stay consistent and safe.
"""

from __future__ import annotations

import html
import re
from typing import Optional


_CONTEXT_SECTION_ID = "raw-context-section"


def append_context_section(
    html_content: str,
    raw_context: Optional[str],
    *,
    max_len: Optional[int] = None,
) -> str:
    """
    Escape and append raw_context to the end of html_content.

    - No-op if raw_context is falsy or html_content is empty.
    - Idempotent: if a section with the marker ID already exists, returns original.
    - Escapes content; optional truncation is applied before escaping.
    - Inserts before the last </body>, else before the last </html>, else appends.
    """
    if not raw_context or not html_content:
        return html_content

    lower_html = html_content.lower()
    if f'id="{_CONTEXT_SECTION_ID}"' in lower_html or f"id='{_CONTEXT_SECTION_ID}'" in lower_html:
        # Already injected; avoid double-append
        return html_content

    context_text = raw_context
    if max_len is not None and max_len > 0 and len(context_text) > max_len:
        overflow = len(context_text) - max_len
        context_text = context_text[:max_len] + f"\n\n...[truncated {overflow} chars]"

    escaped_context = html.escape(context_text)

    context_section = f"""
<hr id="{_CONTEXT_SECTION_ID}" style="margin-top: 40px; border: 1px dashed #ccc;">
<details style="margin-top: 20px; padding: 15px; background: #1a1a2e; border-radius: 8px; color: #a0a0b0;">
<summary style="cursor: pointer; color: #8b8b9e; font-size: 14px; font-weight: bold; margin-bottom: 10px;">
  📋 原始上下文数据（用于生成本报告的聊天记录）
</summary>
<pre style="white-space: pre-wrap; word-wrap: break-word; font-size: 12px; color: #888; background: #0c0c16; padding: 10px; border-radius: 4px; border: 1px solid #2d2d3a; margin-top: 10px; max-height: 500px; overflow-y: auto; font-family: monospace;">
{escaped_context}
</pre>
</details>
"""

    # 1) Prefer explicit anchor if present
    anchor_idx = html_content.find("<!-- CONTEXT_ANCHOR -->")
    if anchor_idx != -1:
        insertion_point = anchor_idx + len("<!-- CONTEXT_ANCHOR -->")
        return html_content[:insertion_point] + context_section + html_content[insertion_point:]

    # 2) Fallback: last </body>
    body_matches = list(re.finditer(r"</body>", html_content, flags=re.IGNORECASE))
    if body_matches:
        last = body_matches[-1]
        return html_content[: last.start()] + context_section + html_content[last.start() :]

    # 3) Fallback: last </html>
    html_matches = list(re.finditer(r"</html>", html_content, flags=re.IGNORECASE))
    if html_matches:
        last = html_matches[-1]
        return html_content[: last.start()] + context_section + html_content[last.start() :]

    # 4) Fallback: append
    return html_content + context_section
