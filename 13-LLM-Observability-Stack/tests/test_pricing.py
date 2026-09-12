from obs.metrics.pricing import PRICES_PATH, ModelRate, estimate_cost, load_prices


def test_known_model_computes_cost() -> None:
    prices = {"gpt-test": ModelRate(in_per_1k=1.0, out_per_1k=2.0)}
    cost, pricing = estimate_cost("gpt-test", 1000, 500, prices=prices)
    assert pricing == "PRICED"
    assert cost == 2.0


def test_unknown_model_is_unpriced() -> None:
    cost, pricing = estimate_cost("some-unknown-model", 100, 100, prices={})
    assert cost is None
    assert pricing == "UNPRICED"


def test_no_model_is_unpriced() -> None:
    cost, pricing = estimate_cost(None, 100, 100, prices={})
    assert cost is None
    assert pricing == "UNPRICED"


def test_missing_token_counts_treated_as_zero() -> None:
    prices = {"gpt-test": ModelRate(in_per_1k=1.0, out_per_1k=2.0)}
    cost, pricing = estimate_cost("gpt-test", None, None, prices=prices)
    assert pricing == "PRICED"
    assert cost == 0.0


def test_existing_cost_is_trusted_over_table() -> None:
    prices = {"gpt-test": ModelRate(in_per_1k=1.0, out_per_1k=2.0)}
    cost, pricing = estimate_cost("gpt-test", 999, 999, existing_cost=0.42, prices=prices)
    assert cost == 0.42
    assert pricing == "PRICED"


def test_ollama_models_default_to_zero_from_config() -> None:
    prices = load_prices(PRICES_PATH)
    cost, pricing = estimate_cost("qwen3.5:0.8b", 1000, 1000, prices=prices)
    assert cost == 0.0
    assert pricing == "PRICED"
