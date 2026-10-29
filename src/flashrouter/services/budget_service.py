class BudgetEnforcement:
    def can_access_model(self, key_id, model_id, allowed_models):
        if not allowed_models or allowed_models == "[]": return True
        allowed = allowed_models if isinstance(allowed_models, list) else __import__("json").loads(str(allowed_models) or "[]")
        return model_id in allowed
    def reserve(self, key_id, cost): return True
