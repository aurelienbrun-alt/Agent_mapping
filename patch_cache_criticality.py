"""patch_cache_criticality.py — inject Essential / Important into existing cache files.

Re-reads the configured Essential and Important columns from each Excel input
file and patches the already-cached AtomicRequirement JSON files in-place.
This lets you enable ENABLE_ENTITY_CRITICALITY=true without rebuilding the
entire cache (no LLM calls needed).

Usage
-----
    python patch_cache_criticality.py            # uses .env by default
    python patch_cache_criticality.py --env path/to/.env
    python patch_cache_criticality.py --dry-run  # preview only, no writes
"""
from __future__ import annotations

import os
import sys


def _relaunch_in_venv() -> None:
    root = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(root, ".venv", "Scripts", "python.exe")
    if not os.path.exists(venv_python):
        return
    if os.path.abspath(sys.executable).lower() == os.path.abspath(venv_python).lower():
        return
    import subprocess
    sys.exit(subprocess.run([venv_python] + sys.argv).returncode)


_relaunch_in_venv()

import argparse
import json
import re
from pathlib import Path

import pandas as pd
from dotenv import dotenv_values


# The three cache checkpoints written by src/cache.py.
_CACHE_FILENAMES = (
    "atomic_requirements.json",
    "atomized_requirements.json",
    "atomic_requirements_with_fields.json",
)

_TRUE_TOKENS  = {"true", "vrai", "1", "yes", "oui", "y", "o", "x", "✓", "✔", "essential", "important"}
_FALSE_TOKENS = {"false", "faux", "0", "no", "non", "n", "", "na", "n/a", "-"}


def _normalize(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def _parse_bool(raw: str, default: bool) -> bool:
    v = _normalize(raw).lower()
    if v in _TRUE_TOKENS:
        return True
    if v in _FALSE_TOKENS:
        return False
    return default


def _build_criticality_map(
    excel_path: Path,
    sheet_name: str,
    id_col: str,
    essential_col: str,
    important_col: str,
) -> dict[str, dict[str, bool]]:
    """Return {source_id: {essential, important}} mirroring excel_io.py logic."""
    if not excel_path.exists():
        print(f"  [WARN] Excel file not found: {excel_path}", flush=True)
        return {}

    df = pd.read_excel(excel_path, sheet_name=sheet_name or 0, dtype=str)
    df.columns = [_normalize(c) for c in df.columns]

    available = list(df.columns)
    for label, col in [("id", id_col), ("essential", essential_col), ("important", important_col)]:
        if col and col not in available:
            print(f"  [WARN] Column '{col}' ({label}) not found in {excel_path.name}.")
            print(f"         Available columns: {available}")

    result: dict[str, dict[str, bool]] = {}
    seen_ids: set[str] = set()

    for idx, row in df.iterrows():
        raw_id = _normalize(row.get(id_col, "")) if id_col else ""
        source_id = raw_id or f"row_{idx + 2}"
        if source_id in seen_ids:
            source_id = f"{source_id}__row_{idx + 2}"
        seen_ids.add(source_id)

        essential = _parse_bool(row.get(essential_col, "") if essential_col else "", default=True)
        important  = _parse_bool(row.get(important_col, "") if important_col else "", default=False)

        result[source_id] = {"essential": essential, "important": important}

    return result


def _patch_file(
    path: Path,
    maps: dict[str, dict[str, dict[str, bool]]],
    dry_run: bool,
) -> tuple[int, int]:
    """Patch one JSON cache file. Returns (total_atoms, patched_atoms)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  [SKIP] Cannot read {path}: {exc}")
        return 0, 0

    if not isinstance(data, list):
        return 0, 0

    patched = 0
    for atom in data:
        if not isinstance(atom, dict):
            continue

        fw  = str(atom.get("framework", "") or "")
        pid = str(atom.get("parent_id",  "") or "")

        # Resolve criticality: first try the atom's own framework, then any.
        crit: dict[str, bool] | None = None
        if fw in maps:
            crit = maps[fw].get(pid)
        if crit is None:
            for fw_map in maps.values():
                crit = fw_map.get(pid)
                if crit is not None:
                    break

        if crit is not None:
            atom["essential"] = crit["essential"]
            atom["important"] = crit["important"]
            patched += 1
        else:
            # Ensure fields exist with safe defaults even if ID not found.
            atom.setdefault("essential", True)
            atom.setdefault("important", False)

    if not dry_run and patched > 0:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    return len(data), patched


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env",     default=".env", help="Path to .env file (default: .env)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    root    = Path(__file__).parent
    env_path = root / args.env
    if not env_path.exists():
        print(f"[ERROR] .env not found: {env_path}")
        sys.exit(1)

    env = dotenv_values(env_path)
    docs_cache_dir = root / (_normalize(env.get("DOCS_CACHE_DIR", "")) or "cache")

    # ── Build per-framework criticality maps ────────────────────────────────
    maps: dict[str, dict[str, dict[str, bool]]] = {}

    for prefix in ("A", "B"):
        fw_name = _normalize(env.get(f"{prefix}_FRAMEWORK_NAME", "") or env.get(f"FRAMEWORK_{prefix}_NAME", "") or prefix)
        file_key = f"{prefix}_FRAMEWORK_FILE"
        excel_str = _normalize(env.get(file_key, "") or env.get(f"{prefix}_FILE", ""))
        if not excel_str:
            print(f"\n[{prefix}] No Excel file configured ({file_key} not set) — skipping.")
            continue

        excel_path    = root / excel_str
        sheet_name    = _normalize(env.get(f"{prefix}_SHEET_NAME", ""))
        id_col        = _normalize(env.get(f"{prefix}_ID_COLUMN",        ""))
        essential_col = _normalize(env.get(f"{prefix}_ESSENTIAL_COLUMN", "Essential"))
        important_col = _normalize(env.get(f"{prefix}_IMPORTANT_COLUMN", "Important"))

        print(f"\n[{prefix}] Framework: {fw_name}")
        print(f"     File     : {excel_path.name}")
        print(f"     Columns  : id={id_col or '(none)'} | essential={essential_col or '(none)'} | important={important_col or '(none)'}")

        cmap = _build_criticality_map(excel_path, sheet_name, id_col, essential_col, important_col)
        print(f"     Loaded   : {len(cmap)} requirements")
        maps[fw_name] = cmap

    if not maps:
        print("\n[ERROR] No frameworks loaded. Check your .env configuration.")
        sys.exit(1)

    # ── Scan and patch cache files ───────────────────────────────────────────
    if not docs_cache_dir.exists():
        print(f"\n[ERROR] Cache directory not found: {docs_cache_dir}")
        sys.exit(1)

    print(f"\nScanning cache: {docs_cache_dir}")
    if args.dry_run:
        print("(dry-run mode — no files will be written)\n")

    total_files  = 0
    total_atoms  = 0
    total_patched = 0

    for filename in _CACHE_FILENAMES:
        for path in sorted(docs_cache_dir.rglob(filename)):
            total_files += 1
            atoms, patched = _patch_file(path, maps, args.dry_run)
            total_atoms   += atoms
            total_patched += patched
            rel = path.relative_to(docs_cache_dir)
            verb = "would patch" if args.dry_run else "patched"
            print(f"  {verb} {patched:>4}/{atoms:<4} atoms   {rel}")

    if total_files == 0:
        print("  No cache files found.")
    else:
        mode = " (dry-run)" if args.dry_run else ""
        print(f"\nDone{mode}: {total_patched}/{total_atoms} atoms updated across {total_files} file(s).")


if __name__ == "__main__":
    main()
