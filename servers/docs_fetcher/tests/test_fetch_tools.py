import pytest

import server
from conftest import FakeResponse

URL = "https://example.dev/page"
OTHER_URL = "https://example.dev/other"


def page(body, title=None):
    head = f"<head><title>{title}</title></head>" if title is not None else ""
    return f"<html>{head}<body>{body}</body></html>"


def long_page(chars):
    return page(f"<p>{'a' * chars}</p>")


# ---------- fetch_url ----------


@pytest.mark.parametrize("bad", ["http://example.dev/", "ftp://example.dev/", "example.dev", "HTTPS://example.dev/"])
def test_fetch_url_rejects_non_https(web, bad):
    assert server.fetch_url(bad) == {"error": "Only https:// URLs are permitted."}
    assert web.calls == []


def test_fetch_url_returns_cleaned_content_with_metadata(web):
    web.add_html(URL, page("<p>Hello</p>", title=" My Title "))

    assert server.fetch_url(URL) == {
        "url": URL,
        "content": "Hello",
        "total_chars": 5,
        "char_offset": 0,
        "note": server.CONTENT_NOTE,
        "title": "My Title",
    }


def test_fetch_url_title_is_none_without_a_title_element(web):
    web.add_html(URL, page("<p>Hello</p>"))

    assert server.fetch_url(URL)["title"] is None


def test_fetch_url_title_is_none_when_title_element_is_empty(web):
    web.add_html(URL, page("<p>Hello</p>", title="   "))

    assert server.fetch_url(URL)["title"] is None


def test_fetch_url_returns_http_errors_unchanged(web):
    web.pages[URL] = FakeResponse(status_code=404)

    assert server.fetch_url(URL) == {"error": f"HTTP 404 fetching {URL}"}


def test_fetch_url_first_window_is_8000_chars_with_truncation_notice(web):
    web.add_html(URL, long_page(20000))

    result = server.fetch_url(URL)

    notice = "\n\n[... truncated. 12000 chars remaining. Call again with char_offset=8000]"
    assert result["content"] == "a" * 8000 + notice
    assert result["total_chars"] == 20000
    assert result["char_offset"] == 0


def test_fetch_url_middle_window_reports_remaining_and_next_offset(web):
    web.add_html(URL, long_page(20000))

    result = server.fetch_url(URL, char_offset=8000)

    notice = "\n\n[... truncated. 4000 chars remaining. Call again with char_offset=16000]"
    assert result["content"] == "a" * 8000 + notice
    assert result["char_offset"] == 8000


def test_fetch_url_last_window_has_no_notice(web):
    web.add_html(URL, long_page(20000))

    result = server.fetch_url(URL, char_offset=16000)

    assert result["content"] == "a" * 4000


@pytest.mark.parametrize("total, offset", [(8000, 0), (16000, 8000)])
def test_fetch_url_window_ending_exactly_at_the_end_has_no_notice(web, total, offset):
    web.add_html(URL, long_page(total))

    result = server.fetch_url(URL, char_offset=offset)

    assert result["content"] == "a" * 8000


def test_fetch_url_offset_beyond_the_end_returns_empty_content(web):
    web.add_html(URL, long_page(20000))

    result = server.fetch_url(URL, char_offset=99999)

    assert result["content"] == ""
    assert result["total_chars"] == 20000
    assert result["char_offset"] == 99999


def test_fetch_url_negative_offset_slices_relative_to_the_end(web):
    web.add_html(URL, long_page(20000))

    result = server.fetch_url(URL, char_offset=-10)

    assert result["content"] == ""
    assert result["char_offset"] == -10


def test_fetch_url_paginating_does_not_refetch(web):
    web.add_html(URL, long_page(20000))

    server.fetch_url(URL)
    server.fetch_url(URL, char_offset=8000)

    assert web.urls == [URL]


def test_fetch_url_warns_when_another_url_returned_identical_content(web):
    web.add_html(URL, page("<p>Same body</p>", title="First"))
    web.add_html(OTHER_URL, page("<p>Same body</p>", title="Second"))

    first = server.fetch_url(URL)
    second = server.fetch_url(OTHER_URL)

    assert "warning" not in first
    assert second["warning"] == (
        f"Content is identical to {URL}, fetched earlier this session. "
        "The site may serve one page for every route; check that this is the page you asked for."
    )
    assert second["title"] == "Second"


def test_fetch_url_no_warning_when_same_url_is_fetched_again(web):
    web.add_html(URL, page("<p>Body</p>"))

    server.fetch_url(URL)
    again = server.fetch_url(URL)

    assert "warning" not in again


def test_fetch_url_no_warning_for_different_content(web):
    web.add_html(URL, page("<p>One</p>"))
    web.add_html(OTHER_URL, page("<p>Two</p>"))

    server.fetch_url(URL)

    assert "warning" not in server.fetch_url(OTHER_URL)


def test_fetch_url_never_warns_for_empty_content(web):
    web.add_html(URL, page(""))
    web.add_html(OTHER_URL, page(""))

    server.fetch_url(URL)
    result = server.fetch_url(OTHER_URL)

    assert result["content"] == ""
    assert "warning" not in result


def test_fetch_url_duplicate_check_compares_full_content_not_the_window(web):
    web.add_html(URL, page(f"<p>{'a' * 20000}</p>"))
    web.add_html(OTHER_URL, page(f"<p>{'a' * 20000}</p>"))

    server.fetch_url(URL, char_offset=0)
    result = server.fetch_url(OTHER_URL, char_offset=16000)

    assert result["warning"].startswith(f"Content is identical to {URL}")


# ---------- fetch_docs ----------


def register(name="foo", url="https://foo.dev/docs/"):
    server.add_library(name, url)


def test_fetch_docs_unknown_library_lists_available_keys(web):
    register("foo")
    register("baz", "https://baz.dev/")

    assert server.fetch_docs("bar") == {"error": "Unknown library 'bar'. Available: ['foo', 'baz']"}
    assert web.calls == []


def test_fetch_docs_with_empty_registry_lists_no_keys(web):
    assert server.fetch_docs("foo") == {"error": "Unknown library 'foo'. Available: []"}


def test_fetch_docs_lowercases_library_name(web):
    register("foo")
    web.add_html("https://foo.dev/docs", page("<p>Docs</p>"))

    result = server.fetch_docs("FOO")

    assert result["library"] == "foo"
    assert result["content"] == "Docs"


def test_fetch_docs_without_topic_strips_trailing_slash_from_base_url(web):
    register("foo", "https://foo.dev/docs/")
    web.add_html("https://foo.dev/docs", page("<p>Docs</p>"))

    result = server.fetch_docs("foo")

    assert web.urls == ["https://foo.dev/docs"]
    assert result["url"] == "https://foo.dev/docs"


@pytest.mark.parametrize("topic", ["torch.nn", "/torch.nn", "torch.nn/", "/torch.nn/"])
def test_fetch_docs_joins_topic_with_single_slash(web, topic):
    register("foo", "https://foo.dev/docs/")
    web.add_html("https://foo.dev/docs/torch.nn", page("<p>nn</p>"))

    result = server.fetch_docs("foo", topic=topic)

    assert web.urls == ["https://foo.dev/docs/torch.nn"]
    assert result["url"] == "https://foo.dev/docs/torch.nn"


def test_fetch_docs_topic_may_contain_nested_path(web):
    register("foo", "https://foo.dev/docs")
    web.add_html("https://foo.dev/docs/a/b.html", page("<p>nested</p>"))

    assert server.fetch_docs("foo", topic="a/b.html")["content"] == "nested"


def test_fetch_docs_returns_same_fields_as_fetch_url_plus_library(web):
    register("foo", "https://foo.dev/docs/")
    web.add_html("https://foo.dev/docs", page("<p>Docs</p>", title="Docs title"))

    assert server.fetch_docs("foo") == {
        "url": "https://foo.dev/docs",
        "library": "foo",
        "content": "Docs",
        "total_chars": 4,
        "char_offset": 0,
        "note": server.CONTENT_NOTE,
        "title": "Docs title",
    }


def test_fetch_docs_paginates_like_fetch_url(web):
    register("foo", "https://foo.dev/docs/")
    web.add_html("https://foo.dev/docs", long_page(20000))

    result = server.fetch_docs("foo", char_offset=8000)

    notice = "\n\n[... truncated. 4000 chars remaining. Call again with char_offset=16000]"
    assert result["content"] == "a" * 8000 + notice


def test_fetch_docs_propagates_fetch_errors(web):
    register("foo", "https://foo.dev/docs/")
    web.pages["https://foo.dev/docs"] = FakeResponse(status_code=403)

    result = server.fetch_docs("foo")

    assert result["error"].startswith("HTTP 403 fetching https://foo.dev/docs - the site is blocking")


def test_fetch_docs_does_not_require_https_for_hand_edited_registry_entries(web):
    server.LIBRARIES_PATH.write_text('{"insecure": "http://insecure.dev/docs/"}')
    web.add_html("http://insecure.dev/docs", page("<p>plain http</p>"))

    result = server.fetch_docs("insecure")

    assert result["content"] == "plain http"
    assert web.urls == ["http://insecure.dev/docs"]
