from __future__ import annotations

import pandas as pd

from .config import FrameworkConfig, AppConfig
from .models import RequirementRow
from .utils import normalize_text, normalize_category


def _configured_columns(cfg: FrameworkConfig) -> dict[str, str]:
    """Return only columns explicitly configured in .env.

    Empty values such as A_SUBCATEGORY_COLUMN= mean "this field does not exist in
    the Excel file" and must not be validated against df.columns.
    """
    return {
        "id": normalize_text(cfg.id_column),
        "title": normalize_text(cfg.title_column),
        "requirement": normalize_text(cfg.requirement_column),
        "category": normalize_text(cfg.category_column),
        "subcategory": normalize_text(cfg.subcategory_column),
    }


def _cell(row, column_name: str) -> str:
    if not column_name:
        return ""
    return normalize_text(row.get(column_name))


_TRUE_TOKENS = {"true", "vrai", "1", "yes", "oui", "y", "o", "x", "✓", "✔", "essential", "important"}
_FALSE_TOKENS = {"false", "faux", "0", "no", "non", "n", "", "na", "n/a", "-"}


def _cell_bool(row, column_name: str, default: bool) -> bool:
    """Parse a True/False criticality cell. Empty/unknown values fall back to default."""
    if not column_name:
        return default
    raw = normalize_text(row.get(column_name)).strip().lower()
    if raw in _TRUE_TOKENS:
        return True
    if raw in _FALSE_TOKENS:
        return False
    return default


def read_framework_excel(cfg: FrameworkConfig, app_cfg: AppConfig) -> list[RequirementRow]:
    if not cfg.file.exists():
        raise FileNotFoundError(f"Excel file not found: {cfg.file}")

    df = pd.read_excel(cfg.file, sheet_name=cfg.sheet_name or 0, dtype=str)
    columns = _configured_columns(cfg)

    # The requirement column is the only truly mandatory field.
    # ID, title, category and subcategory may be left empty in .env.
    if not columns["requirement"]:
        raise ValueError(
            f"Missing requirement column configuration for {cfg.file.name}. "
            "Set A_REQUIREMENT_COLUMN or B_REQUIREMENT_COLUMN in .env."
        )

    missing = [
        col
        for col in columns.values()
        if col and col not in df.columns
    ]
    if missing:
        available = list(df.columns)
        raise ValueError(
            f"Missing columns in {cfg.file.name}: {missing}. Check .env column names. "
            f"Available columns are: {available}"
        )

    # Entity criticality columns are validated only when the feature is enabled.
    essential_col = normalize_text(cfg.essential_column) if app_cfg.enable_entity_criticality else ""
    important_col = normalize_text(cfg.important_column) if app_cfg.enable_entity_criticality else ""
    if app_cfg.enable_entity_criticality:
        crit_missing = [c for c in (essential_col, important_col) if c and c not in df.columns]
        if crit_missing:
            raise ValueError(
                f"ENABLE_ENTITY_CRITICALITY=true but missing column(s) in {cfg.file.name}: {crit_missing}. "
                f"Set A_ESSENTIAL_COLUMN/A_IMPORTANT_COLUMN (and B_*) in .env or disable the feature. "
                f"Available columns are: {list(df.columns)}"
            )

    if app_cfg.max_requirements_per_framework > 0:
        df = df.head(app_cfg.max_requirements_per_framework)

    rows: list[RequirementRow] = []
    seen_ids: set[str] = set()
    for idx, row in df.iterrows():
        requirement = _cell(row, columns["requirement"])
        source_id = _cell(row, columns["id"]) or f"row_{idx + 2}"
        if not requirement:
            continue
        if source_id in seen_ids:
            source_id = f"{source_id}__row_{idx + 2}"
        seen_ids.add(source_id)

        category = _cell(row, columns["category"])
        subcategory = _cell(row, columns["subcategory"])

        # Essential is always True in the source data; Important defaults to False when absent.
        essential = _cell_bool(row, essential_col, default=True)
        important = _cell_bool(row, important_col, default=False)

        rows.append(
            RequirementRow(
                framework=cfg.name,
                source_id=source_id,
                title=_cell(row, columns["title"]),
                requirement=requirement,
                category=category,
                category_key=normalize_category(
                    category,
                    case_sensitive=app_cfg.category_case_sensitive,
                    trim_spaces=app_cfg.category_trim_spaces,
                ),
                subcategory=subcategory,
                row_number=int(idx) + 2,
                essential=essential,
                important=important,
            )
        )
    return rows
