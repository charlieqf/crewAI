import re


def parse_context_window(value: str) -> int | None:
    match = re.fullmatch(r"(\d+)([hdw])", value.strip().lower())
    if not match:
        return None
    amount = int(match.group(1))
    unit = match.group(2)
    seconds = {"h": 3600, "d": 86400, "w": 604800}[unit]
    return amount * seconds
