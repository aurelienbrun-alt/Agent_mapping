from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import FrameworkConfig, AppConfig
from .models import AtomicRequirement
from .utils import file_sha256, read_json, safe_filename, stable_hash, write_json


FULL_CACHE_FILE = "atomic_requirements.json"
ATOMIZED_CACHE_FILE = "atomized_requirements.json"
FIELDS_CACHE_FILE = "atomic_requirements_with_fields.json"
CACHE_METADATA_FILE = "cache_metadata.json"
PROCESSING_REPORT_FILE = "processing_report.json"
CACHE_SCHEMA_VERSION = "framework_cache_v4_input_validated"


def _cache_model_payload(app_cfg: AppConfig) -> dict[str, Any]:
    return {
        "provider": "azure_openai",
        "text": getattr(app_cfg, "azure_openai_text_deployment", ""),
        "judge": getattr(app_cfg, "azure_openai_judge_deployment", ""),
        "category": getattr(app_cfg, "azure_openai_category_deployment", ""),
        "embedding": getattr(app_cfg, "azure_openai_embedding_deployment", ""),
        "embedding_dimensions": getattr(app_cfg, "azure_openai_embedding_dimensions", 0),
    }


def _framework_metadata(framework_cfg: FrameworkConfig, app_cfg: AppConfig) -> dict[str, Any]:
    return {
        "schema": CACHE_SCHEMA_VERSION,
        "framework_name": framework_cfg.name,
        "source_file": str(framework_cfg.file),
        "source_file_name": framework_cfg.file.name,
        "source_file_sha256": file_sha256(framework_cfg.file) if framework_cfg.file.exists() else "",
        "sheet_name": framework_cfg.sheet_name or "",
        "columns": {
            "id": framework_cfg.id_column,
            "title": framework_cfg.title_column,
            "requirement": framework_cfg.requirement_column,
            "category": framework_cfg.category_column,
            "subcategory": framework_cfg.subcategory_column,
        },
        "models": _cache_model_payload(app_cfg),
        # Atomization/extraction prompts affect framework cache. Pairwise/final judge
        # prompts do not, so changing mapping logic does not force atomization reruns.
        "prompt_hashes": {
            "atomize": stable_hash(app_cfg.prompt_atomize),
            "extract": stable_hash(app_cfg.prompt_extract_fields),
            "keyword_normalization": stable_hash(app_cfg.prompt_keyword_normalization),
        },
        "keyword_language_normalization": {
            "enabled": bool(app_cfg.normalize_language_for_keyword_matching),
            "pivot_language": app_cfg.pivot_language,
            "use_llm": bool(app_cfg.use_llm_keyword_normalization),
        },
    }


def framework_cache_key(framework_cfg: FrameworkConfig, app_cfg: AppConfig) -> str:
    # Strict hash cache still uses all framework preprocessing inputs.
    return stable_hash(_framework_metadata(framework_cfg, app_cfg))


def cache_dir(framework_cfg: FrameworkConfig, app_cfg: AppConfig) -> Path:
    """Return the cache directory for a framework.

    CACHE_KEY_MODE controls cache naming only. v4 adds optional strict metadata
    validation so a file_name cache cannot silently reuse a cache from a
    different Excel file.
    """
    mode = getattr(app_cfg, "cache_key_mode", "hash") or "hash"
    mode = mode.strip().lower()
    if mode in {"file", "file_name", "filename"}:
        return app_cfg.docs_cache_dir / safe_filename(framework_cfg.file.stem)
    if mode in {"framework", "framework_name", "name"}:
        return app_cfg.docs_cache_dir / safe_filename(framework_cfg.name)

    key = framework_cache_key(framework_cfg, app_cfg)
    return app_cfg.docs_cache_dir / f"{safe_filename(framework_cfg.name)}_{key}"


def cache_mode_description(app_cfg: AppConfig) -> str:
    return (getattr(app_cfg, "cache_key_mode", "hash") or "hash").strip().lower()


def _atoms_from_json(data: list[dict[str, Any]]) -> list[AtomicRequirement]:
    atoms: list[AtomicRequirement] = []
    for item in data:
        allowed = set(AtomicRequirement.__dataclass_fields__.keys())
        clean = {k: v for k, v in item.items() if k in allowed}
        clean.setdefault("keyword_text", "")
        clean.setdefault("embedding", [])
        clean.setdefault("fields", {})
        clean.setdefault("original_category", clean.get("category", ""))
        clean.setdefault("category_harmonization_reason", "")
        clean.setdefault("category_harmonization_confidence", 0.0)
        clean.setdefault("secondary_categories", [])
        clean.setdefault("category_scores", {})
        atoms.append(AtomicRequirement(**clean))
    return atoms


def _metadata_file(cdir: Path) -> Path:
    return cdir / CACHE_METADATA_FILE


def _load_metadata(cdir: Path) -> dict[str, Any]:
    for filename in [CACHE_METADATA_FILE, PROCESSING_REPORT_FILE]:
        path = cdir / filename
        if not path.exists():
            continue
        try:
            data = read_json(path)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


def _write_metadata(cdir: Path, framework_cfg: FrameworkConfig, app_cfg: AppConfig, extra: dict[str, Any] | None = None) -> None:
    meta = _framework_metadata(framework_cfg, app_cfg)
    if extra:
        meta.update(extra)
    write_json(_metadata_file(cdir), meta)


def _cache_is_compatible(framework_cfg: FrameworkConfig, app_cfg: AppConfig, filename: str) -> tuple[bool, str]:
    """Return whether a cache file can be used for the current input.

    In file_name/framework_name modes, this prevents the historical bug where a
    new Excel file reused an old cache because the folder name matched.
    """
    if app_cfg.rebuild_cache:
        return False, "REBUILD_CACHE=true"
    if not getattr(app_cfg, "strict_input_cache_validation", True):
        return True, "strict_validation_disabled"

    cdir = cache_dir(framework_cfg, app_cfg)
    meta = _load_metadata(cdir)
    if not meta:
        return False, "missing_cache_metadata"

    expected = _framework_metadata(framework_cfg, app_cfg)
    # These fields must match to reuse atomization/fields/embeddings safely.
    checks = [
        ("source_file_sha256", expected.get("source_file_sha256"), meta.get("source_file_sha256")),
        ("sheet_name", expected.get("sheet_name"), meta.get("sheet_name", "")),
        ("columns", expected.get("columns"), meta.get("columns")),
        ("embedding_model", expected.get("models", {}).get("embedding"), meta.get("models", {}).get("embedding")),
        ("embedding_dimensions", expected.get("models", {}).get("embedding_dimensions"), meta.get("models", {}).get("embedding_dimensions")),
    ]
    # Prompt hashes are allowed to be absent in old caches only if the user has disabled strict validation.
    checks.append(("prompt_hashes", expected.get("prompt_hashes"), meta.get("prompt_hashes")))
    for name, expected_value, actual_value in checks:
        if expected_value != actual_value:
            return False, f"metadata_mismatch:{name}"
    return True, "metadata_ok"


def _load_atoms_file(framework_cfg: FrameworkConfig, app_cfg: AppConfig, filename: str) -> list[AtomicRequirement] | None:
    path = cache_dir(framework_cfg, app_cfg) / filename
    if not path.exists():
        return None
    ok, reason = _cache_is_compatible(framework_cfg, app_cfg, filename)
    if not ok:
        return None
    data = read_json(path)
    if not isinstance(data, list):
        return None
    return _atoms_from_json(data)


def _save_atoms_file(framework_cfg: FrameworkConfig, app_cfg: AppConfig, filename: str, atoms: list[AtomicRequirement]) -> None:
    cdir = cache_dir(framework_cfg, app_cfg)
    cdir.mkdir(parents=True, exist_ok=True)
    write_json(cdir / filename, [asdict(a) for a in atoms])
    _write_metadata(cdir, framework_cfg, app_cfg, {"last_checkpoint_file": filename, "atomic_requirements": len(atoms)})


def load_processed_cache(framework_cfg: FrameworkConfig, app_cfg: AppConfig) -> list[AtomicRequirement] | None:
    return _load_atoms_file(framework_cfg, app_cfg, FULL_CACHE_FILE)


def load_atomized_cache(framework_cfg: FrameworkConfig, app_cfg: AppConfig) -> list[AtomicRequirement] | None:
    return _load_atoms_file(framework_cfg, app_cfg, ATOMIZED_CACHE_FILE)


def load_fields_cache(framework_cfg: FrameworkConfig, app_cfg: AppConfig) -> list[AtomicRequirement] | None:
    return _load_atoms_file(framework_cfg, app_cfg, FIELDS_CACHE_FILE)


def save_atomized_cache(framework_cfg: FrameworkConfig, app_cfg: AppConfig, atoms: list[AtomicRequirement]) -> None:
    _save_atoms_file(framework_cfg, app_cfg, ATOMIZED_CACHE_FILE, atoms)


def save_fields_cache(framework_cfg: FrameworkConfig, app_cfg: AppConfig, atoms: list[AtomicRequirement]) -> None:
    _save_atoms_file(framework_cfg, app_cfg, FIELDS_CACHE_FILE, atoms)


def save_processed_cache(framework_cfg: FrameworkConfig, app_cfg: AppConfig, atoms: list[AtomicRequirement], metadata: dict[str, Any]) -> None:
    cdir = cache_dir(framework_cfg, app_cfg)
    cdir.mkdir(parents=True, exist_ok=True)
    full_meta = _framework_metadata(framework_cfg, app_cfg)
    full_meta.update(metadata)
    full_meta["atomic_requirements"] = len(atoms)
    write_json(cdir / FULL_CACHE_FILE, [asdict(a) for a in atoms])
    write_json(cdir / PROCESSING_REPORT_FILE, full_meta)
    write_json(cdir / CACHE_METADATA_FILE, full_meta)
