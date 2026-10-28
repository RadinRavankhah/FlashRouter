"""Admin API request/response models."""

from __future__ import annotations

from pydantic import BaseModel


class LoginRequest(BaseModel):
    api_key: str
