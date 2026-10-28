"""Operational logging helpers."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

LOGGER_NAME = "flashrouter"


def configure_logging(level: str = "info") -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=numeric_level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    else:
        root.setLevel(numeric_level)
    logging.getLogger(LOGGER_NAME).setLevel(numeric_level)


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def new_request_id() -> str:
    return uuid.uuid4().hex


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    text = str(value).replace("\n", " ").replace("\r", " ")
    return text if len(text) <= 160 else f"{text[:157]}..."


class LoggingRequestLogSink:
    """v0.1 log sink: emits a compact operational line, stores nothing."""

    def __init__(self) -> None:
        self._logger = get_logger()

    def record(self, event: Mapping[str, Any]) -> None:
        fields = " ".join(f"{key}={_format_value(value)}" for key, value in event.items())
        self._logger.info("request_event %s", fields)
