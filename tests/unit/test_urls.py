from flashrouter.transport.urls import join_url


def test_join_with_v1_root():
    assert (
        join_url("https://openrouter.ai/api/v1", "chat/completions")
        == "https://openrouter.ai/api/v1/chat/completions"
    )


def test_join_inserts_v1_when_no_path():
    assert (
        join_url("https://api.openai.com", "chat/completions")
        == "https://api.openai.com/v1/chat/completions"
    )


def test_join_keeps_trailing_root():
    assert (
        join_url("http://127.0.0.1:1234/v1/", "/models")
        == "http://127.0.0.1:1234/v1/models"
    )
