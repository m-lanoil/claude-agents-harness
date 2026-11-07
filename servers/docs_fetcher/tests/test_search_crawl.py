import pytest

import server
from conftest import FakeResponse

BASE = "https://x.dev/docs/"


def page(body):
    return f"<html><body>{body}</body></html>"


def links(*hrefs):
    return "".join(f'<a href="{h}">link</a>' for h in hrefs)


# ---------- search_docs ----------


@pytest.fixture
def lib(web):
    server.add_library("lib", BASE)
    return web


def test_search_docs_unknown_library(web):
    server.add_library("known", BASE)

    assert server.search_docs("nope", "x") == {"error": "Unknown library 'nope'. Available: ['known']"}
    assert web.calls == []


def test_search_docs_returns_matching_snippets_and_ignores_removed_tags(lib):
    lib.add_html(
        "https://x.dev/docs",
        page("<nav>Install nav</nav><p>How to install the package</p><p>install again</p><p>other</p>"),
    )

    result = server.search_docs("lib", "install")

    assert result == {
        "url": "https://x.dev/docs",
        "query": "install",
        "total_matches": 2,
        "snippets_returned": 2,
        "snippets": ["How to install the package", "install again"],
        "note": server.CONTENT_NOTE,
    }


def test_search_docs_is_case_insensitive_and_lowercases_library(lib):
    lib.add_html("https://x.dev/docs", page("<p>Install me</p>"))

    result = server.search_docs("LIB", "INSTALL")

    assert result["snippets"] == ["Install me"]
    assert result["query"] == "INSTALL"


def test_search_docs_query_is_a_regex(lib):
    lib.add_html("https://x.dev/docs", page("<p>torch.nn</p><p>torchXnn</p><p>other</p>"))

    result = server.search_docs("lib", r"torch.nn")

    assert result["snippets"] == ["torch.nn", "torchXnn"]


def test_search_docs_without_matches_returns_short_result_without_note(lib):
    lib.add_html("https://x.dev/docs", page("<p>nothing here</p>"))

    assert server.search_docs("lib", "zebra") == {
        "url": "https://x.dev/docs",
        "query": "zebra",
        "snippets": [],
        "total_matches": 0,
    }


def test_search_docs_invalid_regex_is_reported_after_the_page_is_fetched(lib):
    lib.add_html("https://x.dev/docs", page("<p>text</p>"))

    result = server.search_docs("lib", "(")

    assert result["error"].startswith("Invalid regex pattern:")
    assert lib.urls == ["https://x.dev/docs"]


def test_search_docs_joins_topic_to_base_url(lib):
    lib.add_html("https://x.dev/docs/api/index.html", page("<p>found</p>"))

    result = server.search_docs("lib", "found", topic="/api/index.html")

    assert result["url"] == "https://x.dev/docs/api/index.html"


def test_search_docs_propagates_fetch_errors(lib):
    lib.pages["https://x.dev/docs"] = FakeResponse(status_code=500)

    assert server.search_docs("lib", "x") == {"error": "HTTP 500 fetching https://x.dev/docs"}


def test_search_docs_snippet_is_the_immediate_parent_text_only(lib):
    lib.add_html("https://x.dev/docs", page("<p>before <b>match</b> after</p>"))

    result = server.search_docs("lib", "match")

    assert result["snippets"] == ["match"]


def test_search_docs_collapses_whitespace_in_snippets(lib):
    lib.add_html("https://x.dev/docs", page("<p>a   match\n\n  here</p>"))

    assert server.search_docs("lib", "match")["snippets"] == ["a match here"]


def test_search_docs_snippets_are_cut_at_400_chars(lib):
    lib.add_html("https://x.dev/docs", page(f"<p>match {'x' * 1000}</p>"))

    snippet = server.search_docs("lib", "match")["snippets"][0]

    assert len(snippet) == 400
    assert snippet.startswith("match xxx")


def test_search_docs_duplicate_snippets_are_returned_once_but_all_matches_counted(lib):
    lib.add_html("https://x.dev/docs", page("<p>dup item</p><p>dup item</p><p>dup item</p>"))

    result = server.search_docs("lib", "item")

    assert result["total_matches"] == 3
    assert result["snippets_returned"] == 1
    assert result["snippets"] == ["dup item"]


def test_search_docs_returns_at_most_ten_snippets_but_counts_every_match(lib):
    body = "".join(f"<p>item {i}</p>" for i in range(25))
    lib.add_html("https://x.dev/docs", page(body))

    result = server.search_docs("lib", "item")

    assert result["total_matches"] == 25
    assert result["snippets_returned"] == 10
    assert result["snippets"] == [f"item {i}" for i in range(10)]


def test_search_docs_only_inspects_the_first_twenty_matches(lib):
    body = "".join("<p>dup item</p>" for _ in range(20)) + "<p>late item</p>"
    lib.add_html("https://x.dev/docs", page(body))

    result = server.search_docs("lib", "item")

    assert result["total_matches"] == 21
    assert result["snippets"] == ["dup item"]


# ---------- crawl_docs ----------


@pytest.mark.parametrize("bad", ["http://x.dev/docs/", "x.dev/docs/"])
def test_crawl_docs_rejects_non_https(web, bad):
    assert server.crawl_docs(bad) == {"error": "Only https:// URLs are permitted."}
    assert web.calls == []


def build_site(web):
    web.add_html(
        BASE,
        page(
            links(
                "/docs/a",
                "b",
                "#frag",
                "mailto:me@x.dev",
                "https://other.dev/docs/z",
                "/blog/c",
                "/docs/a#top",
            )
        ),
    )
    web.add_html("https://x.dev/docs/a", page("<p>Alpha Torch</p>"))
    web.add_html("https://x.dev/docs/b", page("<p>Beta</p>"))
    web.add_html("https://x.dev/blog/c", page("<p>Gamma</p>"))


def test_crawl_docs_follows_same_domain_links_under_the_prefix(web):
    build_site(web)

    result = server.crawl_docs(BASE)

    assert web.urls == [BASE, "https://x.dev/docs/a", "https://x.dev/docs/b"]
    assert result["pages_visited"] == 3
    assert result["pages_matched"] == 3
    assert [p["url"] for p in result["pages"]] == web.urls
    assert result["pages"][1]["content"] == "Alpha Torch"
    assert result["note"] == server.CONTENT_NOTE


def test_crawl_docs_without_same_prefix_follows_other_paths_on_the_same_domain(web):
    build_site(web)

    result = server.crawl_docs(BASE, same_prefix=False)

    assert web.urls == [BASE, "https://x.dev/docs/a", "https://x.dev/docs/b", "https://x.dev/blog/c"]
    assert result["pages_visited"] == 4


def test_crawl_docs_never_leaves_the_starting_domain(web):
    build_site(web)

    server.crawl_docs(BASE, same_prefix=False)

    assert "https://other.dev/docs/z" not in web.urls


def test_crawl_docs_stops_at_max_pages(web):
    build_site(web)

    result = server.crawl_docs(BASE, max_pages=2)

    assert web.urls == [BASE, "https://x.dev/docs/a"]
    assert result["pages_visited"] == 2


def test_crawl_docs_with_zero_max_pages_visits_nothing(web):
    result = server.crawl_docs(BASE, max_pages=0)

    assert result == {"pages_visited": 0, "pages_matched": 0, "pages": [], "note": server.CONTENT_NOTE}
    assert web.calls == []


def test_crawl_docs_caps_max_pages_at_30(web):
    web.add_html(BASE, page(links("p1")))
    for i in range(1, 41):
        web.add_html(f"https://x.dev/docs/p{i}", page(f"<p>page {i}</p>" + links(f"p{i + 1}")))

    result = server.crawl_docs(BASE, max_pages=100)

    assert result["pages_visited"] == 30
    assert len(web.calls) == 30


def test_crawl_docs_keywords_filter_pages_but_still_follow_their_links(web):
    build_site(web)

    result = server.crawl_docs(BASE, keywords=["TORCH"])

    assert result["pages_visited"] == 3
    assert result["pages_matched"] == 1
    assert [p["url"] for p in result["pages"]] == ["https://x.dev/docs/a"]


def test_crawl_docs_keywords_match_any(web):
    build_site(web)

    result = server.crawl_docs(BASE, keywords=["nomatch", "beta"])

    assert [p["url"] for p in result["pages"]] == ["https://x.dev/docs/b"]


def test_crawl_docs_counts_failed_pages_as_visited_but_omits_them(web):
    web.add_html(BASE, page(links("ok", "gone")))
    web.add_html("https://x.dev/docs/ok", page("<p>fine</p>"))
    web.pages["https://x.dev/docs/gone"] = FakeResponse(status_code=404)

    result = server.crawl_docs(BASE)

    assert result["pages_visited"] == 3
    assert [p["url"] for p in result["pages"]] == [BASE, "https://x.dev/docs/ok"]


def test_crawl_docs_truncates_page_content_over_3000_chars(web):
    web.add_html(BASE, page(f"<p>{'y' * 5000}</p>"))

    result = server.crawl_docs(BASE)

    assert result["pages"][0]["content"] == "y" * 3000 + "\n[... truncated]"


def test_crawl_docs_keeps_content_of_exactly_3000_chars(web):
    web.add_html(BASE, page(f"<p>{'y' * 3000}</p>"))

    assert server.crawl_docs(BASE)["pages"][0]["content"] == "y" * 3000


def test_crawl_docs_prefix_is_the_full_start_path_not_its_directory(web):
    web.add_html("https://x.dev/docs/intro", page(links("/docs/other", "/docs/intro/sub")))
    web.add_html("https://x.dev/docs/intro/sub", page("<p>sub</p>"))

    result = server.crawl_docs("https://x.dev/docs/intro")

    assert web.urls == ["https://x.dev/docs/intro", "https://x.dev/docs/intro/sub"]
    assert result["pages_visited"] == 2


def test_crawl_docs_page_entries_have_only_url_and_content(web):
    web.add_html(BASE, page("<p>x</p>"))

    assert server.crawl_docs(BASE)["pages"] == [{"url": BASE, "content": "x"}]
