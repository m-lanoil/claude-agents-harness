import httpx
import pytest

from conftest import API_KEY, FakeResponse
from mcp_helpers import call_tool, call_tool_error, list_tool_names

SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

BRAVE_PAYLOAD = {
    "query": {"original": "fastmcp testing", "altered": "fastmcp test", "more_results_available": True},
    "web": {
        "results": [
            {
                "title": "Testing",
                "url": "https://example.com/a",
                "description": "About testing",
                "age": "2 days ago",
                "page_age": "2026-11-10T00:00:00",
                "extra": "dropped",
            },
            {"title": "Bare", "url": "https://example.com/b"},
        ]
    },
}


def test_server_exposes_only_web_search():
    assert list_tool_names() == ["web_search"]


# ----------------------------------------------------------- input validation


@pytest.fixture
def no_network(brave, monkeypatch):
    """Validation must fail before any request is made."""

    def forbidden(*args, **kwargs):
        raise AssertionError("httpx.get must not be called when input is invalid")

    monkeypatch.setattr(httpx, "get", forbidden)


@pytest.mark.parametrize("query", ["", "   ", "\n\t"])
def test_blank_query_is_rejected(no_network, query):
    assert "query must not be empty" in call_tool_error("web_search", {"query": query})


def test_query_over_600_characters_is_rejected(no_network):
    message = call_tool_error("web_search", {"query": "a" * 601})
    assert "600 characters" in message and "75 words" in message


def test_query_over_75_words_is_rejected_even_when_short_in_characters(no_network):
    query = " ".join(["a"] * 76)
    assert len(query) < 600
    assert "75 words" in call_tool_error("web_search", {"query": query})


def test_query_at_both_limits_is_accepted(brave):
    brave.outcome = FakeResponse(payload=BRAVE_PAYLOAD)
    call_tool("web_search", {"query": "a" * 600})
    call_tool("web_search", {"query": " ".join(["a"] * 75)})
    assert len(brave.calls) == 2


def test_length_limit_is_measured_after_stripping(brave):
    brave.outcome = FakeResponse(payload=BRAVE_PAYLOAD)
    call_tool("web_search", {"query": "  " + "a" * 600 + "  "})
    assert len(brave.params["q"]) == 600


@pytest.mark.parametrize("count", [0, -1, 21, 100])
def test_count_outside_1_to_20_is_rejected(no_network, count):
    assert "count must be between 1 and 20" in call_tool_error("web_search", {"query": "x", "count": count})


@pytest.mark.parametrize("count", [1, 20])
def test_count_bounds_are_accepted(brave, count):
    brave.outcome = FakeResponse(payload=BRAVE_PAYLOAD)
    call_tool("web_search", {"query": "x", "count": count})
    assert brave.params["count"] == str(count)


@pytest.mark.parametrize("offset", [-1, 10, 50])
def test_offset_outside_0_to_9_is_rejected(no_network, offset):
    assert "offset must be between 0 and 9" in call_tool_error("web_search", {"query": "x", "offset": offset})


@pytest.mark.parametrize("offset", [0, 9])
def test_offset_bounds_are_accepted(brave, offset):
    brave.outcome = FakeResponse(payload=BRAVE_PAYLOAD)
    call_tool("web_search", {"query": "x", "offset": offset})
    assert brave.params["offset"] == str(offset)


# ------------------------------------------------------------------- API key


@pytest.mark.parametrize("value", [None, ""])
def test_missing_or_empty_api_key_is_rejected_before_any_request(brave, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    else:
        monkeypatch.setenv("BRAVE_SEARCH_API_KEY", value)

    message = call_tool_error("web_search", {"query": "x"})

    assert "BRAVE_SEARCH_API_KEY is not set" in message
    assert brave.calls == []


def test_validation_errors_come_before_the_api_key_check(brave, monkeypatch):
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    assert "count must be" in call_tool_error("web_search", {"query": "x", "count": 0})


# ----------------------------------------------------------------- HTTP errors


def test_http_error_status_and_body_are_reported(brave):
    brave.outcome = FakeResponse(status_code=429, text="rate limited")
    assert "Brave Search returned HTTP 429: rate limited" in call_tool_error("web_search", {"query": "x"})


def test_http_error_body_is_truncated_to_300_characters(brave):
    brave.outcome = FakeResponse(status_code=500, text="y" * 500)
    message = call_tool_error("web_search", {"query": "x"})
    assert "y" * 300 in message
    assert "y" * 301 not in message


def test_http_error_message_never_contains_the_api_key(brave):
    brave.outcome = FakeResponse(status_code=401, text="unauthorized")
    assert API_KEY not in call_tool_error("web_search", {"query": "x"})


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("refused", request=httpx.Request("GET", SEARCH_URL)),
        httpx.ReadTimeout("slow", request=httpx.Request("GET", SEARCH_URL)),
    ],
)
def test_transport_errors_report_only_the_exception_type(brave, error):
    brave.outcome = error
    message = call_tool_error("web_search", {"query": "x"})
    assert f"Request to Brave Search failed: {type(error).__name__}" in message
    assert "refused" not in message and "slow" not in message


# ------------------------------------------------------------------- request


def test_request_url_params_headers_and_timeout(brave):
    brave.outcome = FakeResponse(payload=BRAVE_PAYLOAD)

    call_tool("web_search", {"query": "  fastmcp testing  ", "count": 5, "offset": 2})

    url, kwargs = brave.calls[0]
    assert url == SEARCH_URL
    assert kwargs["params"] == {
        "q": "fastmcp testing",
        "count": "5",
        "offset": "2",
        "result_filter": "web",
        "text_decorations": "false",
    }
    assert kwargs["headers"] == {"X-Subscription-Token": API_KEY, "Accept": "application/json"}
    assert kwargs["timeout"] == 15


def test_defaults_are_count_10_offset_0_and_no_freshness(brave):
    brave.outcome = FakeResponse(payload=BRAVE_PAYLOAD)
    call_tool("web_search", {"query": "x"})
    assert brave.params["count"] == "10"
    assert brave.params["offset"] == "0"
    assert "freshness" not in brave.params


def test_freshness_is_forwarded_when_given(brave):
    brave.outcome = FakeResponse(payload=BRAVE_PAYLOAD)
    call_tool("web_search", {"query": "x", "freshness": "pw"})
    assert brave.params["freshness"] == "pw"


# ------------------------------------------------------------------ response


def test_results_are_reduced_to_the_five_documented_fields(brave):
    brave.outcome = FakeResponse(payload=BRAVE_PAYLOAD)

    data = call_tool("web_search", {"query": "fastmcp testing"}).data

    assert data["query"] == "fastmcp testing"
    assert data["altered_query"] == "fastmcp test"
    assert data["more_results_available"] is True
    assert data["count_returned"] == 2
    assert data["results"][0] == {
        "title": "Testing",
        "url": "https://example.com/a",
        "description": "About testing",
        "age": "2 days ago",
        "page_age": "2026-11-10T00:00:00",
    }
    assert data["results"][1] == {
        "title": "Bare",
        "url": "https://example.com/b",
        "description": None,
        "age": None,
        "page_age": None,
    }


def test_response_always_carries_the_unverified_note(brave):
    brave.outcome = FakeResponse(payload=BRAVE_PAYLOAD)
    note = call_tool("web_search", {"query": "x"}).data["note"]
    assert "unverified" in note and "untrusted" in note


@pytest.mark.parametrize("payload", [{}, {"web": None, "query": None}, {"web": {}}])
def test_missing_web_section_gives_zero_results_and_echoes_the_query(brave, payload):
    brave.outcome = FakeResponse(payload=payload)

    data = call_tool("web_search", {"query": "  needle  "}).data

    assert data["results"] == []
    assert data["count_returned"] == 0
    assert data["query"] == "needle"
    assert data["altered_query"] is None
