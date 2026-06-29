"""Import a custom framework: validate an uploaded Excel, persist it, register it.

The pipeline requires the standard NIS2 columns documented in data/README.md
(ID, Title, Requirement, Category). They are matched case-insensitively, and the
*actual* column names found in the file are stored on the catalog entry, so files
with slightly different casing still work.
"""
from __future__ import annotations

import io
import re

import pandas as pd

from src.utils import project_root, safe_filename

from .catalog import FrameworkEntry, custom_dir, list_frameworks, register_custom_framework

REQUIRED_COLUMNS = ["ID", "Title", "Requirement", "Category"]

_COLUMN_DESCRIPTIONS: dict[str, str] = {
    "ID":          "identifiant unique de l'exigence (ex. « CYF-001 »)",
    "Title":       "intitulé du contrôle dans le référentiel (ex. « CyFun 2025 »)",
    "Requirement": "texte détaillé de l'exigence",
    "Category":    "catégorie de l'exigence dans ce référentiel",
}


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _detect_columns(columns: list[str]) -> tuple[dict[str, str], list[str]]:
    """Return (mapping from required name → actual column name, list of missing required names)."""
    by_norm = {_norm(c): c for c in columns}
    mapping: dict[str, str] = {}
    missing: list[str] = []
    for required in REQUIRED_COLUMNS:
        actual = by_norm.get(_norm(required))
        if actual is None:
            missing.append(required)
        else:
            mapping[required] = actual
    return mapping, missing


def add_custom_framework(*, raw: bytes, display_name: str, country: str) -> FrameworkEntry:
    display_name = (display_name or "").strip()
    if not display_name:
        raise ValueError("Le nom du framework est requis.")

    # Validate the workbook in memory before writing anything to disk.
    try:
        df = pd.read_excel(io.BytesIO(raw), sheet_name=0, dtype=str)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Fichier Excel illisible : {exc}") from None

    mapping, missing = _detect_columns(list(df.columns))
    if missing:
        col_list = "\n".join(
            f"  • {col} — {_COLUMN_DESCRIPTIONS[col]}" for col in REQUIRED_COLUMNS
        )
        found = ", ".join(str(c) for c in df.columns) or "(aucune)"
        raise ValueError(
            f"Colonnes manquantes : {', '.join(missing)}\n\n"
            f"Votre fichier doit contenir ces 4 colonnes (la casse est ignorée) :\n"
            f"{col_list}\n\n"
            f"Colonnes trouvées dans votre fichier : {found}"
        )

    req_col = mapping["Requirement"]
    count = int(df[req_col].fillna("").astype(str).str.strip().ne("").sum())
    if count == 0:
        raise ValueError("Aucune exigence trouvée dans la colonne Requirement.")

    # Allocate unique id + filename.
    slug = safe_filename(display_name) or "framework"
    existing_ids = {e.id for e in list_frameworks()}
    fid = f"custom_{slug.lower()}"
    base_id, i = fid, 2
    while fid in existing_ids:
        fid = f"{base_id}_{i}"
        i += 1

    cdir = custom_dir()
    cdir.mkdir(parents=True, exist_ok=True)
    file_path = cdir / f"{slug}.xlsx"
    j = 2
    while file_path.exists():
        file_path = cdir / f"{slug}_{j}.xlsx"
        j += 1
    file_path.write_bytes(raw)

    entry = FrameworkEntry(
        id=fid,
        name=file_path.stem,  # unique; used for cache/output naming
        display_name=display_name,
        country=(country or "").strip() or "—",
        file=str(file_path.relative_to(project_root())).replace("\\", "/"),
        requirement_count=count,
        description="Framework importé",
        sheet_name="",
        id_column=mapping["ID"],
        title_column=mapping["Title"],
        requirement_column=mapping["Requirement"],
        category_column=mapping["Category"],
        available=True,
        custom=True,
    )
    register_custom_framework(entry)
    return entry
