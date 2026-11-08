import pytest

import server
from conftest import FakeResponse

URL = "https://example.dev/page.md"

MARKDOWN = (
    "# Rules\n\n"
    "Use `Edit(<path>)` and `/<YOUR_PROJECT_ROOT>/x` in rules.\n\n"
    "| Rule | Example |\n|---|---|\n"
    "| `Bash(git *)` | `git -c core.fsmonitor='<script>' status` |\n\n"
    "Text after the script mention must survive.\n"
)


def serve(web, body, content_type):
    web.pages[URL] = FakeResponse(text=body, headers={"content-type": content_type})


@pytest.mark.parametrize("content_type", ["text/markdown", "text/markdown; charset=utf-8", "text/plain", "TEXT/PLAIN; charset=UTF-8"])
def test_markdown_and_plain_text_come_back_whole(web, content_type):
    serve(web, MARKDOWN, content_type)

    result = server.fetch_url(URL)

    assert "Text after the script mention must survive." in result["content"]
    assert "Edit(<path>)" in result["content"]
    assert "/<YOUR_PROJECT_ROOT>/x" in result["content"]
    assert "<script>" in result["content"]


def test_markdown_has_no_title(web):
    serve(web, "# Heading\n\nBody text.", "text/markdown")

    assert server.fetch_url(URL)["title"] is None


def test_long_markdown_with_a_script_mention_paginates_to_the_end(web):
    body = "start\n\n`<script>`\n\n" + "\n".join(f"line {i} " + "word " * 20 for i in range(400))
    serve(web, body, "text/markdown")
    cleaned_length = len(server._clean_html(server._PlainText(body)))

    first = server.fetch_url(URL)
    last = server.fetch_url(URL, char_offset=cleaned_length - 100)

    assert first["total_chars"] == cleaned_length
    assert cleaned_length > 8000
    assert last["content"].rstrip().endswith("word")


def test_markdown_is_stored_as_plain_text(web):
    serve(web, MARKDOWN, "text/markdown")

    server.fetch_url(URL)

    assert isinstance(server._cache[URL], server._PlainText)


def test_html_pages_are_still_cleaned(web):
    html = "<html><body><script>var x = 1;</script><nav>Menu</nav><p>Escaped: &lt;path&gt; stays.</p></body></html>"
    serve(web, html, "text/html; charset=utf-8")

    result = server.fetch_url(URL)

    assert result["content"] == "Escaped: <path> stays."
    assert not isinstance(server._cache[URL], server._PlainText)


def test_other_content_types_are_still_treated_as_html(web):
    serve(web, "<html><body><script>x</script><p>Kept</p></body></html>", "application/xhtml+xml")

    assert server.fetch_url(URL)["content"] == "Kept"


def test_crawl_docs_on_a_markdown_page_keeps_the_whole_text(web):
    serve(web, MARKDOWN, "text/markdown")

    result = server.crawl_docs(URL)

    assert result["pages_visited"] == 1
    assert "Text after the script mention must survive." in result["pages"][0]["content"]
