import subprocess

import server
from conftest import FakeResponse


def test_stats_are_empty_before_any_fetch():
    assert server.get_fetch_stats() == {
        "urls_fetched": [],
        "fetch_count": 0,
        "total_chars": 0,
        "estimated_tokens": 0,
        "session_note": "0 URLs fetched, ~0 estimated tokens this session.",
    }


def test_stats_count_one_page_with_singular_wording(web):
    html = "<p>" + "a" * 393 + "</p>"
    assert len(html) == 400
    web.add_html("https://x.dev/one", html)

    server.fetch_url("https://x.dev/one")

    assert server.get_fetch_stats() == {
        "urls_fetched": ["https://x.dev/one"],
        "fetch_count": 1,
        "total_chars": 400,
        "estimated_tokens": 100,
        "session_note": "1 URL fetched, ~100 estimated tokens this session.",
    }


def test_stats_sum_raw_html_length_and_floor_the_token_estimate(web):
    web.add_html("https://x.dev/a", "a" * 500)
    web.add_html("https://x.dev/b", "b" * 501)

    server.fetch_url("https://x.dev/a")
    server.fetch_url("https://x.dev/b")

    stats = server.get_fetch_stats()
    assert stats["urls_fetched"] == ["https://x.dev/a", "https://x.dev/b"]
    assert stats["fetch_count"] == 2
    assert stats["total_chars"] == 1001
    assert stats["estimated_tokens"] == 250
    assert stats["session_note"] == "2 URLs fetched, ~250 estimated tokens this session."


def test_stats_note_uses_thousands_separator(web):
    web.add_html("https://x.dev/big", "a" * 4000)

    server.fetch_url("https://x.dev/big")

    assert server.get_fetch_stats()["session_note"] == "1 URL fetched, ~1,000 estimated tokens this session."


def test_stats_count_raw_html_not_the_cleaned_text_returned(web):
    html = "<html><body><script>" + "s" * 900 + "</script><p>hi</p></body></html>"
    web.add_html("https://x.dev/raw", html)

    result = server.fetch_url("https://x.dev/raw")

    assert result["total_chars"] == 2
    assert server.get_fetch_stats()["total_chars"] == len(html)


def test_stats_do_not_count_repeat_fetches_of_the_same_url(web):
    web.add_html("https://x.dev/a", "a" * 100)

    server.fetch_url("https://x.dev/a")
    server.fetch_url("https://x.dev/a", char_offset=10)

    stats = server.get_fetch_stats()
    assert stats["fetch_count"] == 1
    assert stats["total_chars"] == 100


def test_stats_do_not_count_failed_fetches(web):
    web.pages["https://x.dev/missing"] = FakeResponse(status_code=404)

    server.fetch_url("https://x.dev/missing")

    assert server.get_fetch_stats()["fetch_count"] == 0
    assert server.get_fetch_stats()["urls_fetched"] == []


def test_stats_count_pdf_extracted_text_length(web, monkeypatch):
    web.pages["https://x.dev/doc.pdf"] = FakeResponse(
        content=b"%PDF-1.4 body", headers={"content-type": "application/pdf"}
    )
    monkeypatch.setattr(server.shutil, "which", lambda name: "/usr/bin/pdftotext")
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            args=a[0], returncode=0, stdout=b"x" * 40, stderr=b""
        ),
    )

    server.fetch_url("https://x.dev/doc.pdf")

    stats = server.get_fetch_stats()
    assert stats["total_chars"] == 40
    assert stats["estimated_tokens"] == 10


def test_stats_include_pages_visited_by_crawl_docs(web):
    web.add_html("https://x.dev/docs/", "<p>start</p>")

    server.crawl_docs("https://x.dev/docs/")

    assert server.get_fetch_stats()["urls_fetched"] == ["https://x.dev/docs/"]
