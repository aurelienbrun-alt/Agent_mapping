"""Framework catalog — built-in frameworks plus user-imported ones.

Built-ins are declared below. Imported frameworks are persisted to `data/custom/`
(the Excel file) + `data/custom/registry.json` (the metadata), so they survive
restarts and become selectable like the built-ins.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from src.utils import project_root


@dataclass(frozen=True)
class FrameworkEntry:
    id: str  # stable slug used by the UI / URLs
    name: str  # internal name passed to the pipeline (FRAMEWORK_*_NAME)
    display_name: str  # human label on the card
    country: str
    file: str  # path relative to project root
    requirement_count: int  # static metadata for the card description
    description: str = ""
    sheet_name: str = ""  # "" => first sheet
    id_column: str = "ID"
    title_column: str = "Title"
    requirement_column: str = "Requirement"
    category_column: str = "Category"
    available: bool = True
    custom: bool = False  # True for user-imported frameworks


_BUILTIN: list[FrameworkEntry] = [
    FrameworkEntry(
        id="belgium_cyfun_2025",
        name="Belgique_Cyfun_2025",
        display_name="Belgium CyFun 2025",
        country="Belgium",
        file="data/Belgium_Cyfun_2025.xlsx",
        requirement_count=218,
        description="CyberFundamentals 2025 — Belgian NIS2 transposition",
    ),
    FrameworkEntry(
        id="france_2_3",
        name="France_2.5",
        display_name="France ReCyf 2.5",
        country="France",
        file="data/France_ReCyf_2.5.xlsx",
        requirement_count=152,
        description="ANSSI 2.5 framework — French NIS2 transposition",
    ),
    FrameworkEntry(
        id="netherlands_cbw_nis2",
        name="Pays-Bas_CBw_NIS2",
        display_name="Netherlands CBw NIS2",
        country="Netherlands",
        file="data/Netherland_Cbw_NIS2.xlsx",
        requirement_count=26,
        description="CBw NIS2 Control Framework — Dutch NIS2 transposition",
        id_column="Code",  # this framework uses 'Code' instead of 'ID'
        available=True,
    ),
    FrameworkEntry(
        id="italy_fnsc_2025",
        name="Italie_FNSC_2025_v2",
        display_name="Italy FNSC 2025",
        country="Italy",
        file="data/Italy_FNSC_2025.xlsx",
        requirement_count=160,
        description="National Framework for Cybersecurity and Data Protection Ed. 2025 v2.1.0",
        available=True,
    ),
    FrameworkEntry(
        id="greece_1689",
        name="Grece_1689",
        display_name="Greece Ref. 1689",
        country="Greece",
        file="data/Greece_Ref._1689.xlsx",
        requirement_count=110,
        description="No. 1689 National Cybersecurity Requirements Framework — Key & Important Entities",
        title_column="Tittele",  # source file has this column header (typo in the data)
        available=True,
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
        json.dumps([asdict(e) for e in entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
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
