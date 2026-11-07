import server


def test_plain_text_passes_through_with_blank_lines_and_padding_removed():
    text = server._PlainText("  first line  \n\n   second line\n   \n")

    assert server._clean_html(text) == "first line\nsecond line"


def test_removes_script_style_nav_footer_header_aside():
    html = (
        "<html><body>"
        "<header>HEADERTEXT</header><nav>NAVTEXT</nav><aside>ASIDETEXT</aside>"
        "<p>Body text</p>"
        "<script>var scripttext = 1;</script><style>.styletext {}</style>"
        "<footer>FOOTERTEXT</footer>"
        "</body></html>"
    )

    assert server._clean_html(html) == "Body text"


def test_falls_back_to_whole_document_when_there_is_no_body():
    assert server._clean_html("<p>Just a paragraph</p>") == "Just a paragraph"


def test_lines_are_stripped_and_blank_lines_dropped():
    html = "<html><body><p>  one  </p>\n\n<p>two</p><div>   </div></body></html>"

    assert server._clean_html(html) == "one\ntwo"


def test_single_article_of_at_least_1500_chars_is_chosen_over_body():
    big = "a" * 1600
    html = f"<html><body><div>sidebar words</div><article><p>{big}</p></article></body></html>"

    assert server._clean_html(html) == big


def test_small_article_is_chosen_when_it_is_at_least_a_quarter_of_body_text():
    html = "<html><body><article>Alpha</article><div>Beta</div></body></html>"

    assert server._clean_html(html) == "Alpha"


def test_small_container_under_a_quarter_of_body_text_is_rejected():
    filler = "z" * 200
    html = f"<html><body><main>tiny</main><div>{filler}</div></body></html>"

    assert server._clean_html(html) == f"tiny\n{filler}"


def test_single_article_is_tried_before_main():
    html = (
        "<html><body>"
        f"<main><p>{'m' * 1600}</p></main>"
        f"<article><p>{'a' * 1600}</p></article>"
        "</body></html>"
    )

    assert server._clean_html(html) == "a" * 1600


def test_main_is_tried_before_the_largest_of_several_articles():
    html = (
        "<html><body>"
        f"<main><p>{'m' * 1600}</p></main>"
        "<article>tiny</article>"
        f"<article>{'b' * 1700}</article>"
        "</body></html>"
    )

    assert server._clean_html(html) == "m" * 1600


def test_largest_of_several_articles_is_chosen_when_nothing_else_matches():
    html = (
        "<html><body>"
        "<article>tiny</article>"
        f"<article>{'b' * 1700}</article>"
        "<article>small</article>"
        "</body></html>"
    )

    assert server._clean_html(html) == "b" * 1700


def test_document_class_is_used_when_there_is_no_article_or_main():
    html = f'<html><body><div class="document"><p>{"d" * 1600}</p></div><div>other</div></body></html>'

    assert server._clean_html(html) == "d" * 1600


def test_content_class_is_used_when_there_is_no_article_main_or_document():
    html = f'<html><body><div class="content"><p>{"c" * 1600}</p></div><div>other</div></body></html>'

    assert server._clean_html(html) == "c" * 1600
