"""Shared dependencies.

Azure credentials arrive in request **headers** (the SPA holds them in the browser
and attaches them per call), so they never appear in request bodies/logs and are
never persisted on the server.
"""
from __future__ import annotations

from fastapi import Header

from webapp.core.settings_state import AzureCreds


def get_creds(
    x_azure_api_key: str | None = Header(default=None),
    x_azure_endpoint: str | None = Header(default=None),
    x_azure_api_version: str | None = Header(default=None),
) -> AzureCreds:
    return AzureCreds(
        api_key=(x_azure_api_key or "").strip(),
        endpoint=(x_azure_endpoint or "").strip(),
        api_version=(x_azure_api_version or "").strip(),
    )
