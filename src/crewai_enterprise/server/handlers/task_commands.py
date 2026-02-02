import re

from src.crewai_enterprise.utils.context_window import parse_context_window


def _extract_context_flag(text: str) -> tuple[str, int | None]:
    match = re.search(r"\s*/context:(\S+)", text, re.IGNORECASE)
    if not match:
        return text.strip(), None
    window = parse_context_window(match.group(1))
    cleaned = (text[: match.start()] + text[match.end() :]).strip()
    return cleaned, window


def parse_task_command(text: str):
    stripped = text.strip()
    if not stripped:
        return None
    match = re.match(r"^/task(\d+)\s+(.*)$", stripped)
    if match:
        cleaned, window = _extract_context_flag(match.group(2))
        return {
            "type": "append",
            "task_id": int(match.group(1)),
            "text": cleaned,
            "context_window": window,
        }
    match = re.match(r"^/task\s+(.*)$", stripped)
    if not match:
        return None
    rest = match.group(1).strip()
    if not rest:
        return None
    cleaned, window = _extract_context_flag(rest)
    parts = cleaned.split(maxsplit=1)
    if parts[0].isdigit():
        return {
            "type": "append",
            "task_id": int(parts[0]),
            "text": parts[1] if len(parts) > 1 else "",
            "context_window": window,
        }
    return {"type": "create", "text": cleaned, "context_window": window}
