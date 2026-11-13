import json

import pytest

from conftest import FakeResponse
from mcp_helpers import call_tool_error

ERROR_BODY_CHARS = 300


class NotJsonResponse(FakeResponse):
    def json(self):
        return json.loads(self.text)


def test_non_json_body_is_a_tool_error_with_the_body_prefix(brave):
    body = "<html>" + "x" * 400 + "TAIL"
    brave.outcome = NotJsonResponse(status_code=200, text=body)
    message = call_tool_error("web_search", {"query": "x"})
    assert "not valid JSON" in message
    assert body[:ERROR_BODY_CHARS] in message
    assert "TAIL" not in message


@pytest.mark.parametrize("payload", [["a", "b"], "just a string", 42])
def test_non_object_json_is_an_unexpected_shape_tool_error(brave, payload):
    brave.outcome = FakeResponse(status_code=200, payload=payload)
    assert "unexpected response shape" in call_tool_error("web_search", {"query": "x"})
