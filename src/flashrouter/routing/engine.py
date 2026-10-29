"""Model resolution and account selection."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from flashrouter.errors import model_not_found
from flashrouter.storage.repository import Repository


@dataclass
class Candidate:
    provider_id: int
    provider_name: str
    base_url: str
    protocol: str
    model: str
    headers: dict[str, str] = field(default_factory=dict)


def _headers(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


class Router:
    def __init__(self, repository: Repository) -> None:
        self._repo = repository

    async def resolve(self, requested_model: str) -> list[Candidate]:
        """Resolve a client model name into an ordered list of fallback targets.

        Priority order:
        1. A combo with this name.
        2. ``provider/model`` (provider name prefix; model may contain slashes).
        3. A catalog model id (all providers offering it, by priority).
        """
        model = (requested_model or "").strip()
        if not model:
            raise model_not_found(requested_model)

        combo = await self._repo.find_combo(model)
        if combo and combo["enabled"]:
            targets = await self._repo.combo_candidates(combo["id"])
            candidates = [
                Candidate(
                    provider_id=t["provider_id"],
                    provider_name=t["provider_name"],
                    base_url=t["base_url"],
                    protocol=t["protocol"],
                    model=t["model"],
                    headers=_headers(t.get("headers")),
                )
                for t in targets
            ]
            if candidates:
                return candidates
            raise model_not_found(requested_model)

        if "/" in model:
            prefix, rest = model.split("/", 1)
            provider = await self._repo.find_provider_by_name(prefix)
            if provider and provider["enabled"] and rest:
                return [
                    Candidate(
                        provider_id=provider["id"],
                        provider_name=provider["name"],
                        base_url=provider["base_url"],
                        protocol=provider["protocol"],
                        model=rest,
                        headers=_headers(provider.get("headers")),
                    )
                ]

        rows = await self._repo.models_by_name(model)
        candidates = [
            Candidate(
                provider_id=row["provider_id"],
                provider_name=row["provider_name"],
                base_url=row["base_url"],
                protocol=row["protocol"],
                model=row["model"],
                headers=_headers(row.get("headers")),
            )
            for row in rows
        ]
        if candidates:
            return candidates

        raise model_not_found(requested_model)


def order_accounts(accounts: list[dict[str, Any]], counter: int) -> list[dict[str, Any]]:
    """Order eligible accounts: highest priority tier first, weighted rotation.

    Remaining lower-priority accounts are appended as fallbacks.
    """
    if not accounts:
        return []
    ordered = sorted(accounts, key=lambda a: (-int(a.get("priority", 100)), a["id"]))
    top_priority = int(ordered[0].get("priority", 100))
    tier = [a for a in ordered if int(a.get("priority", 100)) == top_priority]

    expanded: list[dict[str, Any]] = []
    for account in tier:
        expanded.extend([account] * max(1, int(account.get("weight", 1))))
    if not expanded:
        expanded = tier

    start = counter % len(expanded)
    rotated = expanded[start:] + expanded[:start]

    seen: set[int] = set()
    result: list[dict[str, Any]] = []
    for account in rotated:
        if account["id"] in seen:
            continue
        seen.add(account["id"])
        result.append(account)
    for account in ordered:
        if account["id"] not in seen:
            seen.add(account["id"])
            result.append(account)
    return result
