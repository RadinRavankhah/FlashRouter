from flashrouter.routing.engine import order_accounts


def _account(account_id: int, priority: int = 100, weight: int = 1) -> dict:
    return {"id": account_id, "priority": priority, "weight": weight}


def test_higher_priority_first():
    accounts = [_account(1, priority=50), _account(2, priority=100)]
    ordered = order_accounts(accounts, 0)
    assert ordered[0]["id"] == 2


def test_round_robin_rotates_within_tier():
    accounts = [_account(1), _account(2), _account(3)]
    first = order_accounts(accounts, 0)[0]["id"]
    second = order_accounts(accounts, 1)[0]["id"]
    third = order_accounts(accounts, 2)[0]["id"]
    assert {first, second, third} == {1, 2, 3}


def test_lower_priority_appended_as_fallback():
    accounts = [_account(1, priority=100), _account(2, priority=10)]
    ordered = order_accounts(accounts, 0)
    assert [a["id"] for a in ordered] == [1, 2]
