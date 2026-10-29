from flashrouter.services.routing_engine import RoutingEngine

class TestV06:
    def test_select(self):
        r = RoutingEngine()
        c = r.select_candidate("a", [{"enabled":True,"priority":1,"upstream_model":"m"}])
        assert c is not None
    def test_retry_transient(self):
        r = RoutingEngine()
        assert r.retry_policy("timeout", 1) is True
        assert r.retry_policy("timeout", 3) is False
    def test_fallback_no_stream(self):
        r = RoutingEngine()
        assert r.fallback_policy("timeout", False) is True
        assert r.fallback_policy("timeout", True) is False
