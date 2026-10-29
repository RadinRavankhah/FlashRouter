from flashrouter.services.usage import estimate_cost, extract_usage, usage_from_sse_line


def test_extract_usage_chat():
    payload = {"usage": {"prompt_tokens": 12, "completion_tokens": 7}}
    assert extract_usage(payload) == (12, 7)


def test_extract_usage_responses():
    payload = {"usage": {"input_tokens": 3, "output_tokens": 9}}
    assert extract_usage(payload) == (3, 9)


def test_extract_usage_missing():
    assert extract_usage({}) == (0, 0)


def test_estimate_cost():
    cost = estimate_cost(price_in=1.0, price_out=2.0, input_tokens=1_000_000, output_tokens=500_000)
    assert cost == 2.0


def test_usage_from_sse_line():
    assert usage_from_sse_line('data: {"usage": {"prompt_tokens": 1, "completion_tokens": 2}}') == (
        1,
        2,
    )
    assert usage_from_sse_line("data: [DONE]") is None
