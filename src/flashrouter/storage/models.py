"""Row types for the request-history storage layer."""

from __future__ import annotations

from typing import Any


class RequestRow(dict[str, Any]):
    """A single request record from the ``requests`` table."""


class AttemptRow(dict[str, Any]):
    """A single upstream attempt from the ``attempts`` table."""


class PayloadRow(dict[str, Any]):
    """A single body payload from the ``payloads`` table."""


class RequestFilter(dict[str, Any]):
    """Filters for listing requests: model, status, date_from, date_to, request_id."""


class RequestStats(dict[str, Any]):
    """Aggregate statistics for the dashboard overview."""


class StorageHealth(dict[str, Any]):
    """Storage health indicator for the settings page."""
