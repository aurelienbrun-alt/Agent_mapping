"""Framework catalog — built-in NIS2 frameworks plus user-imported ones.

Built-ins (Belgium, France) are hardcoded. Imported frameworks are persisted to
`data/custom/` (the Excel file) + `data/custom/registry.json` (the metadata), so they
survive restarts and become selectable like the built-ins. When a mapping runs,
`config_builder` maps the chosen source/target entries onto the pipeline's A/B slots.

Adding a country later = add a built-in entry; uploading a framework = a registry entry.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

from src.utils import project_root


@dataclass(frozen=True)
class FrameworkEntry:
    id: str                  # stable slug used by the UI / URLs
    name: str                # internal name passed to the pipeline (FRAMEWORK_*_NAME)
    display_name: str        # human label on the card
    country: str
    file: str                # path relative to project root
    requirement_count: int   # static metadata for the card
    description: str = ""
    sheet_name: str = ""     # "" => first sheet
    id_column: str = "ID"
    title_column: str = "Title"
    requirement_column: str = "Requirement"
    category_column: str = "Category"
    available: bool = True
    custom: bool = False      # True for user-imported frameworks


_BUILTIN: list[FrameworkEntry] = [
    FrameworkEntry(
        id="belgium_cyfun_2025",
        name="Belgique_Cyfun_2025",
        display_name="Belgique CyFun 2025",
        country="Belgique",
        file="data/Framework_1_Belgique.xlsx",
        requirement_count=218,
        description="CyberFundamentals 2025 — transposition belge NIS2",
    ),
    FrameworkEntry(
        id="france_2_3",
        name="France_2.3",
        display_name="France 2.3",
        country="France",
        file="data/Framework_2_France.xlsx",
        requirement_count=152,
        description="Référentiel ANSSI 2.3 — transposition française NIS2",
    ),
    FrameworkEntry(
        id="netherlands_cbw_nis2",
        name="Pays-Bas_CBw_NIS2",
        display_name="Pays-Bas CBw NIS2",
        country="Pays-Bas",
        file="",
        requirement_count=0,
        description="CBw NIS2 Control Framework — transposition néerlandaise NIS2",
        available=False,
    ),
    FrameworkEntry(
        id="italy_fnsc_2025",
        name="Italie_FNSC_2025_v2",
        display_name="Italie FNSC 2025",
        country="Italie",
        file="",
        requirement_count=0,
        description="National Framework for Cybersecurity and Data Protection Ed. 2025 v2.1.0",
        available=False,
    ),
    FrameworkEntry(
        id="greece_1689",
        name="Grece_1689",
        display_name="Grèce Réf. 1689",
        country="Grèce",
        file="",
        requirement_count=0,
        description="No. 1689 National Cybersecurity Requirements Framework — Key & Important Entities",
        available=False,
    ),
]


def custom_dir() -> Path:
    return project_root() / "data" / "custom"


def _registry_path() -> Path:
    return custom_dir() / "registry.json"


def _load_custom() -> list[FrameworkEntry]:
    path = _registry_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    allowed = set(FrameworkEntry.__dataclass_fields__.keys())
    entries: list[FrameworkEntry] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        clean = {k: v for k, v in item.items() if k in allowed}
        clean["custom"] = True
        try:
            entries.append(FrameworkEntry(**clean))
        except Exception:
            continue
    return entries


def _save_custom(entries: list[FrameworkEntry]) -> None:
    custom_dir().mkdir(parents=True, exist_ok=True)
    _registry_path().write_text(
        json.dumps([asdict(e) for e in entries], ensure_ascii=False, indent=2), encoding="utf-8"
    )


def list_frameworks() -> list[FrameworkEntry]:
    return list(_BUILTIN) + _load_custom()


def get_framework(framework_id: str) -> FrameworkEntry:
    for entry in list_frameworks():
        if entry.id == framework_id:
            return entry
    raise KeyError(f"Unknown framework id: {framework_id!r}")


def register_custom_framework(entry: FrameworkEntry) -> None:
    customs = [e for e in _load_custom() if e.id != entry.id]
    customs.append(entry)
    _save_custom(customs)


def remove_custom_framework(framework_id: str) -> bool:
    customs = _load_custom()
    keep = [e for e in customs if e.id != framework_id]
    if len(keep) == len(customs):
        return False
    _save_custom(keep)
    # Delete the persisted Excel file (only inside data/custom for safety).
    for e in customs:
        if e.id != framework_id:
            continue
        try:
            path = (project_root() / e.file).resolve()
            if path.exists() and custom_dir().resolve() in path.parents:
                path.unlink()
        except Exception:
            pass
    return True
