import json

from flashrouter.services.usage import (
    Usage,
    estimate_cost,
    extract_usage,
    merge_usage,
    usage_from_sse_line,
)


def test_extract_usage_chat():
    payload = {"usage": {"prompt_tokens": 12, "completion_tokens": 7}}
    assert extract_usage(payload) == Usage(input_tokens=12, output_tokens=7)


def test_extract_usage_responses():
    payload = {"usage": {"input_tokens": 3, "output_tokens": 9}}
    assert extract_usage(payload) == Usage(input_tokens=3, output_tokens=9)


def test_extract_usage_missing():
    assert extract_usage({}) == Usage()


def test_extract_usage_openai_cached_tokens():
    payload = {
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 80},
        }
    }
    assert extract_usage(payload) == Usage(
        input_tokens=100, output_tokens=20, cache_read_tokens=80
    )


def test_extract_usage_deepseek_cache_hit():
    payload = {
        "usage": {
            "prompt_tokens": 50,
            "completion_tokens": 10,
            "prompt_cache_hit_tokens": 40,
        }
    }
    assert extract_usage(payload).cache_read_tokens == 40


def test_extract_usage_anthropic_style_separate_cache():
    payload = {
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 90,
            "cache_creation_input_tokens": 20,
        }
    }
    assert extract_usage(payload) == Usage(
        input_tokens=120,
        output_tokens=5,
        cache_read_tokens=90,
        cache_write_tokens=20,
    )


def test_estimate_cost():
    usage = Usage(input_tokens=1_000_000, output_tokens=500_000)
    cost = estimate_cost(price_in=1.0, price_out=2.0, usage=usage)
    assert cost == 2.0


def test_estimate_cost_discounts_cache_reads():
    usage = Usage(input_tokens=1_000_000, output_tokens=0, cache_read_tokens=800_000)
    cost = estimate_cost(
        price_in=1.0, price_out=2.0, price_cache_in=0.25, usage=usage
    )
    assert cost == 0.4


def test_estimate_cost_falls_back_to_input_price():
    usage = Usage(input_tokens=1_000_000, output_tokens=0, cache_read_tokens=1_000_000)
    cost = estimate_cost(price_in=1.0, price_out=2.0, usage=usage)
    assert cost == 1.0


def test_estimate_cost_bills_cache_writes_at_125x_by_default():
    usage = Usage(input_tokens=1_000_000, output_tokens=0, cache_write_tokens=1_000_000)
    cost = estimate_cost(price_in=1.0, price_out=2.0, usage=usage)
    assert cost == 1.25


def test_estimate_cost_uses_explicit_cache_write_price():
    usage = Usage(input_tokens=1_000_000, output_tokens=0, cache_write_tokens=1_000_000)
    cost = estimate_cost(
        price_in=1.0, price_out=2.0, price_cache_write=2.0, usage=usage
    )
    assert cost == 2.0


def test_usage_from_sse_line():
    assert usage_from_sse_line(
        'data: {"usage": {"prompt_tokens": 1, "completion_tokens": 2}}'
    ) == Usage(input_tokens=1, output_tokens=2)
    assert usage_from_sse_line("data: [DONE]") is None


def test_extract_usage_anthropic_message_start():
    payload = {
        "type": "message_start",
        "message": {
            "usage": {
                "input_tokens": 4,
                "output_tokens": 1,
                "cache_read_input_tokens": 6,
            }
        },
    }
    assert extract_usage(payload) == Usage(
        input_tokens=10, output_tokens=1, cache_read_tokens=6
    )
    assert usage_from_sse_line(f"data: {json.dumps(payload)}") == Usage(
        input_tokens=10, output_tokens=1, cache_read_tokens=6
    )


def test_merge_usage_keeps_input_and_updates_output():
    first = Usage(input_tokens=10, output_tokens=1, cache_read_tokens=4)
    second = Usage(output_tokens=7)
    assert merge_usage(first, second) == Usage(
        input_tokens=10, output_tokens=7, cache_read_tokens=4
    )

