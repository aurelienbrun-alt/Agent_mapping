"""ENISA category list used by the Baseline builder's domain selector.

Read at runtime from the configured ENISA taxonomy workbook (via the existing
`src.category_taxonomy` loader) so the domains stay in sync with the backend's
category model rather than being hardcoded in the UI.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryInfo:
    name: str          # full ENISA category label, e.g. "11 - Access control"
    number: str        # leading number when present, e.g. "11"
    definition: str = ""


def list_enisa_categories() -> list[CategoryInfo]:
    from src.config import load_config
    from src.category_taxonomy import load_enisa_category_cards

    cfg = load_config()
    cards = load_enisa_category_cards(cfg)
    return [CategoryInfo(name=c.category, number=c.number, definition=c.definition) for c in cards]


def category_match_key(value: str) -> str:
    """Normalize a category label for set membership comparison."""
    import re

    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()
