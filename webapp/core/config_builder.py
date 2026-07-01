"""Build an `AppConfig` from a UI selection without touching `.env`.

This is the single seam between the web app and the existing pipeline: it turns a
(source, target, credentials) selection into the `overrides` dict consumed by the
one-line hook added to `src.config.load_config`. Everything else (tuning knobs,
deployment names, prompts) still comes from `.env`.
"""
from __future__ import annotations

from src.config import AppConfig, load_config

from .catalog import FrameworkEntry
from .settings_state import AzureCreds


def _framework_overrides(entry: FrameworkEntry, slot: str) -> dict[str, str]:
    """slot is 'A' (source) or 'B' (target)."""
    return {
        f"FRAMEWORK_{slot}_NAME": entry.name,
        f"FRAMEWORK_{slot}_FILE": entry.file,
        f"{slot}_SHEET_NAME": entry.sheet_name,
        f"{slot}_ID_COLUMN": entry.id_column,
        f"{slot}_TITLE_COLUMN": entry.title_column,
        f"{slot}_REQUIREMENT_COLUMN": entry.requirement_column,
        f"{slot}_CATEGORY_COLUMN": entry.category_column,
    }


def build_overrides(
    source: FrameworkEntry,
    target: FrameworkEntry,
    creds: AzureCreds,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    overrides: dict[str, str] = {}
    overrides.update(_framework_overrides(source, "A"))
    overrides.update(_framework_overrides(target, "B"))
    overrides.update(creds.as_overrides())
    # Bidirectional mapping is required for the product (and for baseline B-only items).
    overrides["BIDIRECTIONAL_MAPPING"] = "true"
    if extra:
        overrides.update(extra)
    return overrides


def build_config(
    source: FrameworkEntry,
    target: FrameworkEntry,
    creds: AzureCreds,
    extra: dict[str, str] | None = None,
) -> AppConfig:
    return load_config(overrides=build_overrides(source, target, creds, extra))
