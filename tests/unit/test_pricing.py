from flashrouter.providers.pricing import ModelPricing, extract_model_pricing


def test_openrouter_per_token_prices():
    item = {
        "id": "openai/gpt-4o",
        "pricing": {
            "prompt": "0.0000025",
            "completion": "0.00001",
            "input_cache_read": "0.00000125",
        },
    }
    assert extract_model_pricing(item) == ModelPricing(2.5, 10.0, 1.25, None)


def test_together_style_per_token_prices():
    item = {"id": "meta-llama/llama-3", "pricing": {"input": 0.00000088, "output": 0.000001}}
    assert extract_model_pricing(item) == ModelPricing(0.88, 1.0, None, None)


def test_prices_already_per_million():
    item = {"id": "m", "pricing": {"input": 0.5, "output": 1.5, "cache_read": 0.1}}
    assert extract_model_pricing(item) == ModelPricing(0.5, 1.5, 0.1, None)


def test_free_model_prices_are_zero():
    item = {"id": "free", "pricing": {"prompt": "0", "completion": "0"}}
    assert extract_model_pricing(item) == ModelPricing(0.0, 0.0, None, None)


def test_missing_pricing_returns_nones():
    assert extract_model_pricing({"id": "m"}) == ModelPricing(None, None, None, None)


def test_openrouter_cache_write_price():
    item = {
        "id": "openai/gpt-5.6",
        "pricing": {
            "prompt": "0.000002",
            "completion": "0.00001",
            "input_cache_read": "0.0000002",
            "input_cache_write": "0.0000025",
        },
    }
    assert extract_model_pricing(item) == ModelPricing(2.0, 10.0, 0.2, 2.5)


def test_invalid_values_fall_through_to_other_keys():
    item = {
        "id": "m",
        "pricing": {"prompt": "n/a", "completion": -1, "input": 2.0, "output": 3.0},
    }
    assert extract_model_pricing(item) == ModelPricing(2.0, 3.0, None, None)
