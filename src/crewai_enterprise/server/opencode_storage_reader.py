import json
import os


def read_new_messages(session_id: str, last_seen_file: str | None, storage_root: str):
    msg_root = os.path.join(storage_root, "message", session_id)
    if not os.path.isdir(msg_root):
        return []
    files = sorted(f for f in os.listdir(msg_root) if f.endswith(".json"))
    chunks = []
    for fname in files:
        path = os.path.join(msg_root, fname)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        info = data.get("info", {})
        msg_id = data.get("id") or info.get("id")
        role = data.get("role") or info.get("role")
        if last_seen_file and fname <= last_seen_file:
            continue
        if role != "assistant":
            continue
        part_dir = os.path.join(storage_root, "part", msg_id)
        if not os.path.isdir(part_dir):
            continue
        text = ""
        for pfile in sorted(os.listdir(part_dir)):
            with open(os.path.join(part_dir, pfile), "r", encoding="utf-8") as pf:
                p = json.load(pf)
            if p.get("type") == "text":
                text += p.get("text", "")
        if text:
            chunks.append({"message_id": msg_id, "text": text, "filename": fname})
    return chunks
