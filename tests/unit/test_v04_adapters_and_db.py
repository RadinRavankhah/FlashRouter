import pytest
from flashrouter.protocols.anthropic_messages import AnthropicMessagesAdapter
from flashrouter.protocols.responses_adapter import ResponsesAdapter
from flashrouter.storage.database import Database, MIGRATIONS, SCHEMA_VERSION
import tempfile, os

class TestAnthropicAdapter:
    def setup_method(self):
        self.a = AnthropicMessagesAdapter()

    def test_name(self):
        assert self.a.name == "anthropic-messages"

    def test_validate_ok(self):
        payload = {"messages": [{"role":"user","content":"hi"}], "stream": False}
        result = self.a.validate_request(payload)
        assert result["messages"][0]["role"] == "user"

    def test_validate_bad_message(self):
        with pytest.raises(Exception):
            self.a.validate_request({"messages": ["bad"]})

    def test_is_stream(self):
        assert self.a.is_stream({"stream": True}) is True
        assert self.a.is_stream({"stream": False}) is False

    def test_prepare_translates_model(self):
        body = self.a.prepare_body({"messages": [{"role":"user","content":"hi"}]}, "claude-3-opus")
        assert body["model"] == "claude-3-opus"

class TestResponsesAdapter:
    def setup_method(self):
        self.a = ResponsesAdapter()

    def test_validate_and_path(self):
        assert self.a.chat_path() == "responses"
        assert self.a.validate_request({"model":"x"})["model"] == "x"

class TestDBMigrationV4:
    def test_schema_version_is_4(self):
        assert SCHEMA_VERSION == 4

    def test_migration_4_exists(self):
        assert 4 in MIGRATIONS
