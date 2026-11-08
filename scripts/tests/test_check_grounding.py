from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture
def cg(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT_DIR))
    import check_grounding

    return check_grounding


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def run_check(cg, deliverable_text, source_texts, ignored=(), min_len=8):
    sources = [cg.normalise(t) for t in source_texts]
    return cg.check(deliverable_text, sources, set(ignored), min_len)


def quotes_of(cg, text, min_len=8):
    return [(n, kind, q) for n, kind, q in cg.extract_quotes(text, min_len)]


# --- extraction -----------------------------------------------------------

def test_extracts_straight_double_quotes(cg):
    assert quotes_of(cg, 'He wrote "a long enough quote" here.') == [
        (1, "quote", "a long enough quote")
    ]


def test_extracts_curly_double_quotes(cg):
    assert quotes_of(cg, "He wrote “a long enough quote” here.") == [
        (1, "quote", "a long enough quote")
    ]


def test_min_len_boundary(cg):
    text = 'exact "12345678" short "1234567"'
    assert quotes_of(cg, text, min_len=8) == [(1, "quote", "12345678")]
    assert quotes_of(cg, text, min_len=7) == [
        (1, "quote", "12345678"),
        (1, "quote", "1234567"),
    ]


def test_single_quotes_are_not_quotes(cg):
    assert quotes_of(cg, "He wrote 'a long enough string' here.") == []


def test_blockquote_marker_stripped(cg):
    assert quotes_of(cg, "> quoted line of text") == [(1, "blockquote", "quoted line of text")]


def test_nested_blockquote_markers_stripped(cg):
    assert quotes_of(cg, ">> > deep quote") == [(1, "blockquote", "deep quote")]


def test_blockquote_lines_are_each_a_quote_and_skip_min_len(cg):
    text = "> Yes.\n> second line here"
    assert quotes_of(cg, text) == [
        (1, "blockquote", "Yes."),
        (2, "blockquote", "second line here"),
    ]


def test_empty_blockquote_line_skipped(cg):
    assert quotes_of(cg, ">\n> ") == []


def test_double_quotes_inside_blockquote_not_scanned_twice(cg):
    found = quotes_of(cg, '> he said "something quite long" today')
    assert found == [(1, "blockquote", 'he said "something quite long" today')]


def test_line_number_inside_multiline_paragraph(cg):
    text = 'first line\nsecond line\nthird has "the quoted text" in it'
    assert quotes_of(cg, text) == [(3, "quote", "the quoted text")]


def test_line_number_after_curly_quotes(cg):
    text = "“first quoted text”\n\n“second quoted text”"
    assert [n for n, _, _ in quotes_of(cg, text)] == [1, 3]


def test_quote_wrapping_across_lines_is_collapsed(cg):
    text = 'a "quote that wraps\nacross   two lines" end'
    assert quotes_of(cg, text) == [(1, "quote", "quote that wraps across two lines")]


def test_stray_quote_does_not_leak_past_blank_line(cg):
    text = 'a stray " mark here\n\nthen "a proper quote" here'
    assert quotes_of(cg, text) == [(3, "quote", "a proper quote")]


def test_results_ordered_by_line(cg):
    text = '> block quote text\n\nplain "inline quote" here'
    assert [n for n, _, _ in quotes_of(cg, text)] == [1, 3]


# --- normalisation --------------------------------------------------------

def test_normalise_collapses_whitespace_and_folds_quotes(cg):
    assert cg.normalise("  a\t“b”\n\n ‘c’  `d` ") == "a \"b\" 'c' 'd'"


def test_whitespace_differences_still_match(cg):
    res = run_check(cg, 'see "alpha beta gamma"', ["alpha\n   beta\tgamma"])
    assert len(res["matched"]) == 1 and not res["unmatched"]


def test_curly_apostrophe_in_source_matches_straight_in_quote(cg):
    res = run_check(cg, 'see "it\'s the thing"', ["it’s the thing"])
    assert len(res["matched"]) == 1


def test_backtick_in_source_matches_apostrophe_in_quote(cg):
    res = run_check(cg, "see \"call 'run' now\"", ["call `run` now"])
    assert len(res["matched"]) == 1


def test_curly_single_quotes_in_source_match_straight_in_quote(cg):
    res = run_check(cg, "see \"say 'hi' loudly\"", ["say ‘hi’ loudly"])
    assert len(res["matched"]) == 1


# --- matching -------------------------------------------------------------

def test_verbatim_quote_matches(cg):
    res = run_check(cg, 'The source says "verbatim words here".', ["xx verbatim words here yy"])
    assert len(res["matched"]) == 1
    assert not res["unmatched"] and not res["case"]


def test_missing_quote_is_unmatched(cg):
    res = run_check(cg, 'The source says "invented words here".', ["something else entirely"])
    assert len(res["unmatched"]) == 1
    assert res["unmatched"][0][0] == 1


def test_case_difference_reported_separately(cg):
    res = run_check(cg, 'see "Verbatim Words Here"', ["verbatim words here"])
    assert len(res["case"]) == 1
    assert not res["matched"] and not res["unmatched"]


def test_matching_is_case_sensitive_when_exact_exists(cg):
    res = run_check(cg, 'see "Verbatim Words"', ["verbatim words", "Verbatim Words"])
    assert len(res["matched"]) == 1 and not res["case"]


def test_match_in_any_source(cg):
    res = run_check(cg, 'see "only in second"', ["first source", "has only in second here"])
    assert len(res["matched"]) == 1


def test_blockquote_checked_against_sources(cg):
    res = run_check(cg, "> found in source\n> not in anything", ["a found in source b"])
    assert [q for _, _, q, _ in res["matched"]] == ["found in source"]
    assert [q for _, _, q, _ in res["unmatched"]] == ["not in anything"]


# --- ellipses -------------------------------------------------------------

def test_each_ellipsis_form_splits_the_quote(cg):
    source = ["the start of it and then the end of it"]
    for marker in ("...", "…", "[...]", "[…]"):
        res = run_check(cg, f'see "the start of it {marker} the end of it"', source)
        assert len(res["matched"]) == 1, marker


def test_ellipsis_fragment_missing_makes_quote_unmatched(cg):
    res = run_check(cg, 'see "the start of it ... a made up end"', ["the start of it and the end"])
    assert len(res["unmatched"]) == 1
    assert res["unmatched"][0][3] == ["a made up end"]


def test_short_fragment_ignored(cg):
    # "xyz" is 3 characters and absent from the source; it must be ignored.
    res = run_check(cg, 'see "the start of it ... xyz"', ["the start of it only"])
    assert len(res["matched"]) == 1


def test_fragment_of_exactly_four_characters_is_checked(cg):
    res = run_check(cg, 'see "the start of it ... wxyz"', ["the start of it only"])
    assert len(res["unmatched"]) == 1


def test_fragments_may_match_in_different_sources(cg):
    res = run_check(cg, 'see "first part here ... second part here"', ["first part here", "second part here"])
    assert len(res["matched"]) == 1


def test_quote_with_only_short_fragments_is_skipped(cg):
    res = run_check(cg, 'see "abc ... def ... ghi"', ["nothing relevant"], min_len=8)
    assert len(res["skipped"]) == 1
    assert not res["unmatched"]


def test_case_only_fragment_makes_case_status(cg):
    res = run_check(cg, 'see "alpha beta ... Gamma delta"', ["alpha beta and gamma delta"])
    assert len(res["case"]) == 1 and not res["unmatched"]


def test_missing_fragment_beats_case_only_fragment(cg):
    res = run_check(cg, 'see "alpha beta ... Gamma delta ... nowhere"', ["alpha beta and gamma delta"])
    assert len(res["unmatched"]) == 1 and not res["case"]


# --- ignore file ----------------------------------------------------------

def test_ignored_quote_not_reported(cg):
    res = run_check(cg, 'see "not evidenced"', ["nothing"], ignored=["not evidenced"])
    assert len(res["ignored"]) == 1
    assert not res["unmatched"]


def test_load_ignore_skips_comments_and_blanks_and_normalises(tmp_path, cg):
    path = write(tmp_path / "ignore.txt", "# comment\n\n  not   evidenced  \n“Curly Label”\n")
    assert cg.load_ignore(path) == {"not evidenced", '"Curly Label"'}


def test_ignore_is_exact_not_substring(cg):
    res = run_check(cg, 'see "not evidenced here"', ["nothing"], ignored=["not evidenced"])
    assert len(res["unmatched"]) == 1


# --- sources --------------------------------------------------------------

def test_load_sources_is_recursive_and_md_only(tmp_path, cg):
    write(tmp_path / "kb" / "a.md", "alpha")
    write(tmp_path / "kb" / "deep" / "b.md", "beta")
    write(tmp_path / "kb" / "c.txt", "gamma")
    sources = cg.load_sources(tmp_path / "kb", [])
    assert sorted(sources) == ["alpha", "beta"]


def test_load_sources_includes_also_of_any_extension(tmp_path, cg):
    write(tmp_path / "kb" / "a.md", "alpha")
    extra = write(tmp_path / "extra.txt", "delta")
    sources = cg.load_sources(tmp_path / "kb", [extra])
    assert sorted(sources) == ["alpha", "delta"]


def test_undecodable_bytes_are_replaced_not_fatal(tmp_path, cg):
    bad = tmp_path / "kb" / "bad.md"
    bad.parent.mkdir()
    bad.write_bytes(b"good words \xff\xfe more words")
    sources = cg.load_sources(tmp_path / "kb", [])
    assert "good words" in sources[0] and "more words" in sources[0]


# --- report ---------------------------------------------------------------

def test_report_sections_in_order_with_counts(cg):
    res = run_check(
        cg,
        'ok "found in source"\nbad "made up words"\ncase "Found In Source"\nign "ignored one"\n',
        ["found in source"],
        ignored=["ignored one"],
    )
    report = "\n".join(cg.build_report(res, 1))
    assert report.index("UNMATCHED (1)") < report.index("CASE DIFFERS (1)") < report.index("COUNTS:")
    assert "line 2 [quote]: made up words" in report
    assert "line 3 [quote]: Found In Source" in report
    assert "4 quotes, 1 matched, 1 case differs, 1 unmatched, 1 ignored, 0 skipped" in report
    assert "NOT CHECKED: attribution, paraphrase, numbers" in report
    assert "Sources read: 1" in report


def test_report_lists_missing_fragments_for_ellipsis_quote(cg):
    res = run_check(cg, 'see "the start of it ... a made up end"', ["the start of it"])
    report = "\n".join(cg.build_report(res, 1))
    assert "not found: a made up end" in report


def test_report_clean_run(cg):
    res = run_check(cg, "no quotes at all", ["x"])
    report = "\n".join(cg.build_report(res, 1))
    assert "UNMATCHED (0)" in report and "0 quotes" in report


# --- main and exit codes --------------------------------------------------

def make_case(tmp_path, deliverable_text, source_text="verbatim words here"):
    write(tmp_path / "kb" / "src.md", source_text)
    deliverable = write(tmp_path / "doc.md", deliverable_text)
    return deliverable, tmp_path / "kb"


def test_exit_0_when_everything_matches(tmp_path, cg):
    doc, kb = make_case(tmp_path, 'see "verbatim words here"')
    assert cg.main([str(doc), "--kb", str(kb)]) == 0


def test_exit_0_when_no_quotes(tmp_path, cg):
    doc, kb = make_case(tmp_path, "plain text only")
    assert cg.main([str(doc), "--kb", str(kb)]) == 0


def test_exit_1_when_unmatched(tmp_path, cg):
    doc, kb = make_case(tmp_path, 'see "invented words here"')
    assert cg.main([str(doc), "--kb", str(kb)]) == 1


def test_case_only_difference_exits_0(tmp_path, cg):
    doc, kb = make_case(tmp_path, 'see "Verbatim Words Here"')
    assert cg.main([str(doc), "--kb", str(kb)]) == 0


def test_ignore_option_turns_exit_1_into_0(tmp_path, cg):
    doc, kb = make_case(tmp_path, 'see "invented words here"')
    ignore = write(tmp_path / "ignore.txt", "invented words here\n")
    assert cg.main([str(doc), "--kb", str(kb), "--ignore", str(ignore)]) == 0


def test_also_option_supplies_extra_source(tmp_path, cg):
    doc, kb = make_case(tmp_path, 'see "from the extra file"')
    extra = write(tmp_path / "extra.txt", "from the extra file")
    assert cg.main([str(doc), "--kb", str(kb)]) == 1
    assert cg.main([str(doc), "--kb", str(kb), "--also", str(extra)]) == 0


def test_also_option_repeatable(tmp_path, cg):
    doc, kb = make_case(tmp_path, 'see "from extra one" and "from extra two"')
    one = write(tmp_path / "one.txt", "from extra one")
    two = write(tmp_path / "two.txt", "from extra two")
    assert cg.main([str(doc), "--kb", str(kb), "--also", str(one), "--also", str(two)]) == 0


def test_min_len_option(tmp_path, cg):
    doc, kb = make_case(tmp_path, 'see "short one"')
    assert cg.main([str(doc), "--kb", str(kb)]) == 1
    assert cg.main([str(doc), "--kb", str(kb), "--min-len", "20"]) == 0


def test_exit_2_missing_deliverable(tmp_path, cg):
    _, kb = make_case(tmp_path, "x")
    assert cg.main([str(tmp_path / "nope.md"), "--kb", str(kb)]) == 2


def test_exit_2_missing_kb_dir(tmp_path, cg):
    doc, _ = make_case(tmp_path, "x")
    assert cg.main([str(doc), "--kb", str(tmp_path / "nope")]) == 2


def test_exit_2_missing_also_file(tmp_path, cg):
    doc, kb = make_case(tmp_path, "x")
    assert cg.main([str(doc), "--kb", str(kb), "--also", str(tmp_path / "nope.txt")]) == 2


def test_exit_2_missing_ignore_file(tmp_path, cg):
    doc, kb = make_case(tmp_path, "x")
    assert cg.main([str(doc), "--kb", str(kb), "--ignore", str(tmp_path / "nope.txt")]) == 2


def test_exit_2_no_sources_found(tmp_path, cg):
    doc = write(tmp_path / "doc.md", 'see "anything at all"')
    empty = tmp_path / "empty_kb"
    empty.mkdir()
    assert cg.main([str(doc), "--kb", str(empty)]) == 2


def test_exit_2_bad_min_len(tmp_path, cg):
    doc, kb = make_case(tmp_path, "x")
    assert cg.main([str(doc), "--kb", str(kb), "--min-len", "0"]) == 2


def test_exit_2_missing_required_kb_argument(tmp_path, cg):
    doc, _ = make_case(tmp_path, "x")
    assert cg.main([str(doc)]) == 2


def test_exit_2_non_integer_min_len(tmp_path, cg):
    doc, kb = make_case(tmp_path, "x")
    assert cg.main([str(doc), "--kb", str(kb), "--min-len", "abc"]) == 2


def test_script_does_not_modify_inputs(tmp_path, cg):
    doc, kb = make_case(tmp_path, 'see "invented words here"')
    before = (doc.read_text(encoding="utf-8"), (kb / "src.md").read_text(encoding="utf-8"))
    cg.main([str(doc), "--kb", str(kb)])
    after = (doc.read_text(encoding="utf-8"), (kb / "src.md").read_text(encoding="utf-8"))
    assert before == after
    assert sorted(p.name for p in tmp_path.iterdir()) == ["doc.md", "kb"]
