import pytest

import server
from conftest import FakeResponse

URL_A = "https://example.dev/a"
URL_B = "https://example.dev/b"
URL_C = "https://example.dev/c"
BASE = "https://x.dev/docs/"


def page(body):
    return f"<html><body><p>{body}</p></body></html>"


def with_cap(monkeypatch, cap):
    monkeypatch.setattr(server, "MAX_URLS", cap)


def add_pages(web, *urls):
    for i, url in enumerate(urls):
        web.add_html(url, page(f"page {i} text"))


# ---------- reading the setting ----------


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_unset_or_empty_setting_means_no_cap(raw):
    assert server._read_cap(raw) == (None, None)


@pytest.mark.parametrize("raw, cap", [("5", 5), (" 12 ", 12), ("1", 1)])
def test_valid_setting_is_a_positive_integer(raw, cap):
    assert server._read_cap(raw) == (cap, None)


@pytest.mark.parametrize("raw", ["abc", "0", "-3", "2.5"])
def test_invalid_setting_is_an_error_with_no_cap(raw):
    cap, error = server._read_cap(raw)

    assert cap is None
    assert error == f"DOCS_FETCHER_MAX_URLS must be a positive integer, got {raw!r}. Fix it and restart the session."


def test_invalid_setting_refuses_every_fetch(web, monkeypatch):
    monkeypatch.setattr(server, "MAX_URLS_ERROR", "bad cap")
    add_pages(web, URL_A)

    result = server.fetch_url(URL_A)

    assert result == {"error": "bad cap", "budget_reached": True}
    assert web.calls == []
    assert server.get_fetch_stats()["fetch_cap_error"] == "bad cap"


# ---------- the gate ----------


def test_without_a_cap_nothing_is_refused_and_stats_have_no_cap_keys(web):
    add_pages(web, URL_A, URL_B, URL_C)

    for url in (URL_A, URL_B, URL_C):
        assert "error" not in server.fetch_url(url)

    stats = server.get_fetch_stats()
    assert "fetch_cap" not in stats and "remaining" not in stats and "urls_attempted" not in stats


def test_a_new_url_beyond_the_cap_is_refused_without_a_request(web, monkeypatch):
    with_cap(monkeypatch, 2)
    add_pages(web, URL_A, URL_B, URL_C)
    server.fetch_url(URL_A)
    server.fetch_url(URL_B)

    result = server.fetch_url(URL_C)

    assert result["budget_reached"] is True
    assert result["error"].startswith("Fetch budget reached (2 distinct URLs).")
    assert "do not retry" in result["error"]
    assert web.urls == [URL_A, URL_B]
    assert URL_C not in server._attempted


def test_repeat_and_cached_urls_are_free_at_the_cap(web, monkeypatch):
    with_cap(monkeypatch, 1)
    add_pages(web, URL_A)
    server.fetch_url(URL_A)

    again = server.fetch_url(URL_A)

    assert "error" not in again
    assert web.urls == [URL_A]


def test_char_offset_pagination_is_free_at_the_cap(web, monkeypatch):
    with_cap(monkeypatch, 1)
    web.add_html(URL_A, page("a" * 20000))

    first = server.fetch_url(URL_A)
    second = server.fetch_url(URL_A, char_offset=8000)

    assert "error" not in first and "error" not in second
    assert len(web.calls) == 1


def test_a_failed_url_counts_against_the_cap(web, monkeypatch):
    with_cap(monkeypatch, 1)
    web.pages[URL_A] = FakeResponse(status_code=403)
    add_pages(web, URL_B)

    failed = server.fetch_url(URL_A)
    refused = server.fetch_url(URL_B)

    assert failed["error"].startswith("HTTP 403")
    assert refused["budget_reached"] is True


def test_retrying_a_failed_url_does_not_count_twice(web, monkeypatch):
    with_cap(monkeypatch, 1)
    web.pages[URL_A] = FakeResponse(status_code=403)

    server.fetch_url(URL_A)
    retry = server.fetch_url(URL_A)

    assert retry["error"].startswith("HTTP 403")
    assert "budget_reached" not in retry
    assert len(web.calls) == 2


def test_fetch_docs_and_search_docs_are_gated_too(web, monkeypatch):
    with_cap(monkeypatch, 1)
    add_pages(web, URL_A, "https://lib.dev/docs", "https://lib2.dev/docs")
    server.add_library("lib", "https://lib.dev/docs")
    server.add_library("lib2", "https://lib2.dev/docs")
    server.fetch_url(URL_A)

    assert server.fetch_docs("lib")["budget_reached"] is True
    assert server.search_docs("lib2", "text")["budget_reached"] is True


# ---------- crawl and stats ----------


def test_crawl_docs_stops_at_the_cap_and_says_so(web, monkeypatch):
    with_cap(monkeypatch, 2)
    web.add_html(BASE, f'<html><body><a href="{BASE}a">a</a><a href="{BASE}b">b</a><p>root</p></body></html>')
    add_pages(web, BASE + "a", BASE + "b")

    result = server.crawl_docs(BASE)

    assert web.urls == [BASE, BASE + "a"]
    assert result["pages_visited"] == 2
    assert result["pages_matched"] == 2
    assert result["stopped"].startswith("Fetch budget reached (2 distinct URLs).")


def test_crawl_docs_has_no_stopped_key_without_a_cap(web):
    web.add_html(BASE, page("root"))

    assert "stopped" not in server.crawl_docs(BASE)


def test_stats_report_the_cap_and_what_remains(web, monkeypatch):
    with_cap(monkeypatch, 3)
    add_pages(web, URL_A, URL_B)
    server.fetch_url(URL_A)
    server.fetch_url(URL_B)

    stats = server.get_fetch_stats()

    assert (stats["fetch_cap"], stats["urls_attempted"], stats["remaining"]) == (3, 2, 1)


def test_stats_remaining_never_goes_below_zero_and_counts_failures(web, monkeypatch):
    with_cap(monkeypatch, 1)
    web.pages[URL_A] = FakeResponse(status_code=403)
    server.fetch_url(URL_A)
    server.fetch_url(URL_B)

    stats = server.get_fetch_stats()

    assert (stats["urls_attempted"], stats["remaining"]) == (1, 0)
    assert stats["fetch_count"] == 0
