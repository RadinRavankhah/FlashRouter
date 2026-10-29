import pytest
from flashrouter.protocols.anthropic_messages import AnthropicMessagesAdapter
from flashrouter.protocols.responses_adapter import ResponsesAdapter

class TestV08V07Finish:
    def test_anthropic_adapter_chat_path(self):
        a = AnthropicMessagesAdapter()
        assert a.chat_path() == "messages"

    def test_responses_adapter_chat_path(self):
        a = ResponsesAdapter()
        assert a.chat_path() == "responses"

    def test_adapter_prepare_keeps_stream(self):
        a = AnthropicMessagesAdapter()
        body = a.prepare_body({"messages":[{"role":"user","content":"hi"}],"stream":True}, "m")
        assert body.get("stream") is True
