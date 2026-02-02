from src.crewai_enterprise.server.handlers.task_commands import parse_task_command


def test_parse_task_command_accepts_task_id_without_space():
    cmd = parse_task_command("/task6 do work")
    assert cmd is not None
    assert cmd["type"] == "append"
    assert cmd["task_id"] == 6
    assert cmd["text"] == "do work"


def test_parse_context_flag():
    cmd = parse_task_command("/task /context:1d do work")
    assert cmd is not None
    assert cmd["context_window"] == 86400
    assert cmd["text"] == "do work"
