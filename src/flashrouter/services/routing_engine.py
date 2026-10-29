class RoutingEngine:
    def select_candidate(self, alias, candidates, budget_ok=True, restrictions_ok=True):
        for c in sorted(candidates, key=lambda x: -x.get("priority",0)):
            if c.get("enabled") and budget_ok and restrictions_ok:
                return c
        return None
    def retry_policy(self, failure_category, attempt_n, max_attempts=3):
        if attempt_n >= max_attempts: return False
        if failure_category in ("timeout","rate_limit","transient"):
            return True
        return False
    def fallback_policy(self, failure_category, stream_started=False):
        if stream_started: return False
        return failure_category in ("timeout","upstream_error","model_unavailable")
