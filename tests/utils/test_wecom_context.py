from src.crewai_enterprise.utils.wecom_context import build_context_summary


def test_context_summary_from_messages():
    messages = [
        {"created_at": "2026-02-01 10:00:00", "sender": "u1", "text": "hello"},
        {"created_at": "2026-02-01 10:01:00", "sender": "u2", "text": "world"},
    ]
    summary = build_context_summary(
        messages, "2026-02-01 00:00:00", "2026-02-02 00:00:00"
    )
    assert summary["count"] == 2
    assert "hello" in summary["first"]
    assert "world" in summary["last"]
