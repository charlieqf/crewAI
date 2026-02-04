import re

from src.crewai_enterprise.utils.context_window import parse_context_window


def extract_context_prefix(text: str) -> tuple[str, int | None]:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return text, None
    tokens = stripped.split()
    context_window = None
    kept: list[str] = []
    for idx, token in enumerate(tokens):
        if not token.startswith("/"):
            kept.extend(tokens[idx:])
            break
        match = re.match(r"^/context:(\S+)$", token, re.IGNORECASE)
        if match:
            window = parse_context_window(match.group(1))
            if window is not None:
                context_window = window
            continue
        kept.append(token)
    return " ".join(kept).strip(), context_window
