from flashrouter.savers.rtk import apply_token_saver, compress_text


def test_dedup_reduces_repeated_lines():
    text = "\n".join(["same line"] * 500)
    compressed = compress_text(text)
    assert len(compressed) < len(text)
    assert "omitted" in compressed


def test_large_output_is_truncated():
    text = "\n".join(f"line {i} " + "x" * 50 for i in range(2000))
    compressed = compress_text(text)
    assert len(compressed) < len(text)


def test_short_text_unchanged():
    assert compress_text("short output") == "short output"


def test_token_saver_targets_tool_messages_only():
    body = {
        "messages": [
            {"role": "system", "content": "x" * 5000},
            {"role": "tool", "content": "\n".join(["dup"] * 400)},
        ]
    }
    result = apply_token_saver(body)
    assert result["messages"][0]["content"] == "x" * 5000
    assert len(result["messages"][1]["content"]) < len(body["messages"][1]["content"])
