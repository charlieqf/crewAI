from src.crewai_enterprise.server.handlers.context_prefix import extract_context_prefix


def test_extract_context_prefix_requires_leading_slash():
    text, window = extract_context_prefix("hello /context:1d")
    assert text == "hello /context:1d"
    assert window is None


def test_extract_context_prefix_uses_last_context_token():
    text, window = extract_context_prefix("/foo /context:1d /bar /context:2h ask")
    assert text == "/foo /bar ask"
    assert window == 7200


def test_extract_context_prefix_strips_invalid_context_token():
    text, window = extract_context_prefix("/context:bad ask")
    assert text == "ask"
    assert window is None


def test_extract_context_prefix_only_scans_prefix_tokens():
    text, window = extract_context_prefix("/context:1d hello /context:2h")
    assert text == "hello /context:2h"
    assert window == 86400
