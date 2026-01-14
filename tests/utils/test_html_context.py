import pytest

from src.crewai_enterprise.utils.html_context import append_context_section


@pytest.fixture(scope="module")
def vcr_cassette_dir(tmp_path_factory):
    # Override project-wide fixture to avoid relative path errors for utility-only tests
    return str(tmp_path_factory.mktemp("cassettes"))


# Local override to bypass global vcr fixture path logic for these simple unit tests
def vcr_config(vcr_cassette_dir: str) -> dict:
    return {
        "cassette_library_dir": vcr_cassette_dir,
        "record_mode": "none",
    }


def test_append_inserts_before_last_body():
    html = "<html><body><div>hi</div></body></html>"
    result = append_context_section(html, "ctx")
    assert result.count("raw-context-section") == 1
    assert result.index("raw-context-section") > result.index("</div>")
    assert result.index("raw-context-section") < result.lower().rfind("</body>")


def test_append_idempotent():
    html = "<html><body><div>hi</div></body></html>"
    once = append_context_section(html, "ctx")
    twice = append_context_section(once, "ctx")
    assert twice.count("raw-context-section") == 1


def test_truncation_applies_before_escape():
    raw = "A" * 10 + "<tag>"
    result = append_context_section("<html><body></body></html>", raw, max_len=5)
    assert "...[truncated" in result
    # Ensure entity is complete (no partial "&lt")
    assert "&lt;tag&gt;" not in result  # because raw was truncated before escaping


def test_append_when_no_closing_tags_appends():
    html = "<html><body><div>hi"
    result = append_context_section(html, "ctx")
    assert result.endswith("ctx\n</pre>\n</details>\n")


def test_anchor_precedence_over_stray_body_tags():
    html = "<html><body><pre>garbage </body></pre><!-- CONTEXT_ANCHOR --></body></html>"
    result = append_context_section(html, "ctx")
    # Should insert at anchor (before last body closing)
    assert result.count("raw-context-section") == 1
    anchor_pos = result.index("<!-- CONTEXT_ANCHOR -->")
    ctx_pos = result.index("raw-context-section")
    assert ctx_pos > anchor_pos
