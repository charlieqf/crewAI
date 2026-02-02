from src.crewai_enterprise.utils.context_window import parse_context_window


def test_parse_context_window_days():
    assert parse_context_window("1d") == 86400


def test_parse_context_window_hours():
    assert parse_context_window("6h") == 21600


def test_parse_context_window_weeks():
    assert parse_context_window("2w") == 1209600


def test_parse_context_window_invalid():
    assert parse_context_window("oops") is None
