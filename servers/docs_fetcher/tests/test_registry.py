import json

import pytest

import server

KINDS = [
    ("add_library", "list_libraries", "LIBRARIES_PATH", "libraries"),
    ("add_cli", "list_clis", "CLIS_PATH", "clis"),
    ("add_other_source", "list_other_sources", "OTHER_SOURCES_PATH", "other_sources"),
]
KIND_IDS = ["libraries", "clis", "other_sources"]
URL = "https://example.dev/docs/"


@pytest.mark.parametrize("add_name, list_name, path_attr, key", KINDS, ids=KIND_IDS)
def test_list_is_empty_when_registry_file_is_missing(add_name, list_name, path_attr, key):
    assert not getattr(server, path_attr).exists()
    assert getattr(server, list_name)() == {key: {}}


@pytest.mark.parametrize("add_name, list_name, path_attr, key", KINDS, ids=KIND_IDS)
def test_add_saves_new_entry_and_writes_indented_json(add_name, list_name, path_attr, key):
    result = getattr(server, add_name)("foo", URL)

    assert result == {"saved": True, "name": "foo", "url": URL}
    assert getattr(server, path_attr).read_text() == json.dumps({"foo": URL}, indent=2)
    assert getattr(server, list_name)() == {key: {"foo": URL}}


@pytest.mark.parametrize("add_name, list_name, path_attr, key", KINDS, ids=KIND_IDS)
def test_add_existing_name_reports_updated_and_replaces_url(add_name, list_name, path_attr, key):
    getattr(server, add_name)("foo", URL)
    result = getattr(server, add_name)("foo", "https://example.dev/v2/")

    assert result == {"updated": True, "name": "foo", "url": "https://example.dev/v2/"}
    assert getattr(server, list_name)() == {key: {"foo": "https://example.dev/v2/"}}


@pytest.mark.parametrize("add_name, list_name, path_attr, key", KINDS, ids=KIND_IDS)
def test_add_lowercases_and_strips_name_but_not_url(add_name, list_name, path_attr, key):
    result = getattr(server, add_name)("  FooBar ", "https://Example.dev/Docs/")

    assert result == {"saved": True, "name": "foobar", "url": "https://Example.dev/Docs/"}
    assert getattr(server, list_name)() == {key: {"foobar": "https://Example.dev/Docs/"}}


@pytest.mark.parametrize("add_name, list_name, path_attr, key", KINDS, ids=KIND_IDS)
def test_add_keeps_existing_entries(add_name, list_name, path_attr, key):
    getattr(server, add_name)("first", "https://one.dev/")
    getattr(server, add_name)("second", "https://two.dev/")

    assert getattr(server, list_name)() == {key: {"first": "https://one.dev/", "second": "https://two.dev/"}}


@pytest.mark.parametrize("bad_url", ["http://example.dev/", "ftp://example.dev/", "example.dev", "", "HTTPS://example.dev/"])
@pytest.mark.parametrize("add_name, list_name, path_attr, key", KINDS, ids=KIND_IDS)
def test_add_rejects_urls_not_starting_with_lowercase_https(add_name, list_name, path_attr, key, bad_url):
    result = getattr(server, add_name)("foo", bad_url)

    assert result == {"error": "Only https:// URLs are permitted."}
    assert not getattr(server, path_attr).exists()


@pytest.mark.parametrize("add_name, list_name, path_attr, key", KINDS, ids=KIND_IDS)
def test_add_accepts_empty_name(add_name, list_name, path_attr, key):
    result = getattr(server, add_name)("   ", URL)

    assert result == {"saved": True, "name": "", "url": URL}
    assert getattr(server, list_name)() == {key: {"": URL}}


def test_registries_are_stored_in_separate_files():
    server.add_library("lib", "https://lib.dev/")
    server.add_cli("tool", "https://tool.dev/")

    assert server.list_libraries() == {"libraries": {"lib": "https://lib.dev/"}}
    assert server.list_clis() == {"clis": {"tool": "https://tool.dev/"}}
    assert server.list_other_sources() == {"other_sources": {}}
    assert not server.OTHER_SOURCES_PATH.exists()


def test_list_reads_hand_edited_registry_file_without_validation():
    server.LIBRARIES_PATH.write_text(json.dumps({"Mixed": "http://insecure.dev/"}))

    assert server.list_libraries() == {"libraries": {"Mixed": "http://insecure.dev/"}}
