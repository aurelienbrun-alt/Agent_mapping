from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import AppConfig, FrameworkConfig
from .models import RequirementRow
from .utils import stable_hash
from .cache import cache_dir
from .logging_utils import JsonlRunLogger
from .azure_openai_client import AzureOpenAIClient
from .category_taxonomy import (
    EnisaCategoryCard,
    apply_category_decision_to_row,
    category_key,
    classify_requirement_category,
    load_category_overrides,
    load_enisa_category_cards,
    taxonomy_hash,
)

# Backward-compatible alias kept for older imports / notebooks.
EnisaCategory = EnisaCategoryCard


def load_enisa_categories(app_cfg: AppConfig) -> list[EnisaCategoryCard]:
    return load_enisa_category_cards(app_cfg)


def harmonize_rows_to_enisa_categories(
    rows: list[RequirementRow],
    framework_cfg: FrameworkConfig,
    app_cfg: AppConfig,
    llm: AzureOpenAIClient,
    logger: JsonlRunLogger,
) -> list[RequirementRow]:
    """Normalize parent rows into the configured ENISA taxonomy.

    This parent-level category is no longer treated as a hard matching filter in
    the recommended soft_enisa mode. It is a prior / reporting field. Atomic
    categories are refined later after atomization and field extraction.
    """
    if not app_cfg.enable_category_harmonization:
        return rows

    cards = load_enisa_category_cards(app_cfg)
    overrides = load_category_overrides(app_cfg)
    cdir = cache_dir(framework_cfg, app_cfg)
    cdir.mkdir(parents=True, exist_ok=True)
    cache_path = cdir / app_cfg.category_harmonization_cache_file
    cache = _load_json(cache_path)

    changed = 0
    llm_or_cached = 0
    deterministic = 0
    low_confidence = 0

    for row in rows:
        original = row.category or ""
        row.original_category = original
        cache_key = _decision_cache_key(row, cards)
        if cache_key in cache and not app_cfg.category_harmonization_force:
            cached = cache[cache_key]
            decision = _cached_decision_to_obj(cached)
            llm_or_cached += 1
        else:
            decision = classify_requirement_category(
                framework=row.framework,
                control_id=row.source_id,
                title=row.title,
                original_category=original,
                requirement=row.requirement,
                fields={},
                keywords=[],
                app_cfg=app_cfg,
                llm=llm,
                cards=cards,
                overrides=overrides,
            )
            cache[cache_key] = decision.as_json()
            if decision.method == "llm_constrained":
                llm_or_cached += 1
            else:
                deterministic += 1

        apply_category_decision_to_row(row, decision, app_cfg)
        if row.category != original:
            changed += 1
        if row.category_harmonization_confidence < app_cfg.category_medium_confidence_threshold:
            low_confidence += 1

    _save_json(cache_path, cache)
    logger.event(
        "category_harmonization.done",
        framework=framework_cfg.name,
        requirements=len(rows),
        changed=changed,
        deterministic=deterministic,
        llm_or_cached=llm_or_cached,
        low_confidence=low_confidence,
        taxonomy=str(app_cfg.enisa_category_file),
        overrides=str(app_cfg.category_overrides_file),
    )
    return rows


def _decision_cache_key(row: RequirementRow, cards: list[EnisaCategoryCard]) -> str:
    payload = {
        "taxonomy": taxonomy_hash(cards),
        "id": row.source_id,
        "category": row.category or "",
        "title": row.title or "",
        "requirement": row.requirement or "",
    }
    return stable_hash(payload)


def _cached_decision_to_obj(data: dict[str, Any]):
    from .category_taxonomy import CategoryDecision

    return CategoryDecision(
        primary_category=str(data.get("primary_category") or data.get("category") or ""),
        secondary_categories=[str(x) for x in data.get("secondary_categories", []) if str(x).strip()] if isinstance(data.get("secondary_categories"), list) else [],
        confidence=float(data.get("confidence") or 0.0),
        method=str(data.get("method") or "cache"),
        reason=str(data.get("reason") or "cache"),
        status=str(data.get("status") or ""),
        scores=data.get("scores") if isinstance(data.get("scores"), dict) else {},
    )


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
