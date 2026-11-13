import httpx
import pytest

from conftest import FakeResponse
from mcp_helpers import call_tool, call_tool_error

PAYLOAD = {"query": {"original": "x"}, "web": {"results": []}}

VALID_FORMS = ["pd", "pw", "pm", "py", "YYYY-MM-DDtoYYYY-MM-DD"]


@pytest.fixture
def no_network(brave, monkeypatch):
    """Validation must fail before any request is made."""

    def forbidden(*args, **kwargs):
        raise AssertionError("httpx.get must not be called when freshness is invalid")

    monkeypatch.setattr(httpx, "get", forbidden)


@pytest.mark.parametrize(
    "given, forwarded",
    [
        ("pd", "pd"),
        ("pw", "pw"),
        ("pm", "pm"),
        ("py", "py"),
        ("2026-01-01to2026-01-31", "2026-01-01to2026-01-31"),
        ("2026-03-05to2026-03-05", "2026-03-05to2026-03-05"),
        ("2030-01-01to2030-12-31", "2030-01-01to2030-12-31"),
        (" pw ", "pw"),
        ("\tpm\n", "pm"),
    ],
)
def test_valid_freshness_is_forwarded_stripped(brave, given, forwarded):
    brave.outcome = FakeResponse(payload=PAYLOAD)
    call_tool("web_search", {"query": "x", "freshness": given})
    assert brave.params["freshness"] == forwarded


@pytest.mark.parametrize("given", ["", "   "])
def test_empty_freshness_adds_no_parameter(brave, given):
    brave.outcome = FakeResponse(payload=PAYLOAD)
    call_tool("web_search", {"query": "x", "freshness": given})
    assert "freshness" not in brave.params


@pytest.mark.parametrize(
    "given",
    [
        "week",
        "PW",
        "pd,pw",
        "2026-01-01",
        "2026-01-01to",
        "2026-1-1to2026-1-31",
        "2026-13-01to2026-14-01",
        "2026-02-30to2026-03-01",
        "2026-03-01to2026-02-01",
    ],
)
def test_invalid_freshness_is_rejected_before_any_request(no_network, given):
    message = call_tool_error("web_search", {"query": "x", "freshness": given})
    assert "freshness must be one of" in message


def test_error_message_names_the_valid_forms(no_network):
    message = call_tool_error("web_search", {"query": "x", "freshness": "week"})
    for form in VALID_FORMS:
        assert form in message


def test_freshness_is_validated_before_the_api_key_check(brave, monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    message = call_tool_error("web_search", {"query": "x", "freshness": "week"})
    assert "freshness must be one of" in message
    assert "BRAVE_SEARCH_API_KEY" not in message
    assert brave.calls == []
