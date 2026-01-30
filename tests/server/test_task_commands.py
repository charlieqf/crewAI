import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.crewai_enterprise.server.handlers.task_commands import parse_task_command


def test_parse_task_create():
    cmd = parse_task_command("/task design a flow")
    assert cmd == {"type": "create", "text": "design a flow"}


def test_parse_task_append():
    cmd = parse_task_command("/task 1234 add note")
    assert cmd == {"type": "append", "task_id": 1234, "text": "add note"}


def test_parse_task_append_empty():
    cmd = parse_task_command("/task 1234")
    assert cmd == {"type": "append", "task_id": 1234, "text": ""}


def test_parse_task_invalid():
    assert parse_task_command("/task") is None
