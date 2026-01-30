import re


def parse_task_command(text: str):
    match = re.match(r"^\s*/task\s+(.*)$", text.strip())
    if not match:
        return None
    rest = match.group(1).strip()
    if not rest:
        return None
    parts = rest.split(maxsplit=1)
    if parts[0].isdigit():
        return {
            "type": "append",
            "task_id": int(parts[0]),
            "text": parts[1] if len(parts) > 1 else "",
        }
    return {"type": "create", "text": rest}
