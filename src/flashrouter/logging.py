"""Operational logging helpers."""

from __future__ import annotations

import logging
import uuid

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
    return "fr_" + uuid.uuid4().hex
