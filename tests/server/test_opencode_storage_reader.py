import sys
from pathlib import Path
import json

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.crewai_enterprise.server.opencode_storage_reader import read_new_messages


def test_read_new_messages(tmp_path):
    msg_dir = tmp_path / "message" / "sess1"
    part_dir = tmp_path / "part" / "msg1"
    part_dir2 = tmp_path / "part" / "msg2"
    msg_dir.mkdir(parents=True)
    part_dir.mkdir(parents=True)
    part_dir2.mkdir(parents=True)
    (msg_dir / "msg1.json").write_text(json.dumps({"role": "assistant", "id": "msg1"}))
    (msg_dir / "msg2.json").write_text(json.dumps({"role": "assistant", "id": "msg2"}))
    (part_dir / "p1.json").write_text(json.dumps({"type": "text", "text": "hello"}))
    (part_dir2 / "p1.json").write_text(json.dumps({"type": "text", "text": "world"}))
    chunks = read_new_messages("sess1", "msg1.json", str(tmp_path))
    assert chunks[0]["text"] == "world"
