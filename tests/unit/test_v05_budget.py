from flashrouter.services.budget_service import BudgetEnforcement

class TestV05:
    def test_restriction_allow(self):
        b = BudgetEnforcement()
        assert b.can_access_model("k","m","[\"m\"]") is True
    def test_restriction_deny(self):
        b = BudgetEnforcement()
        assert b.can_access_model("k","bad","[\"m\"]") is False
