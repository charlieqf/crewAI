from src.crewai_enterprise.server.task_store import TaskStore


def test_task_input_stores_context_fields(tmp_path):
    store = TaskStore(str(tmp_path / "tasks.db"))
    store.init_schema()
    task_id = store.create_task("chat", "user", "title")
    input_id = store.append_input(
        task_id,
        "hello",
        "wecom",
        context_source="wecom",
        context_window=86400,
    )
    inp = store.get_input(input_id)
    assert inp is not None
    assert inp["context_source"] == "wecom"
    assert inp["context_window"] == 86400
