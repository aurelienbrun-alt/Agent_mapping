"""patch_cache_criticality.py — inject Essential / Important into existing cache files.

Autodiscovers every cache folder under DOCS_CACHE_DIR by reading its
processing_report.json (which records the source Excel file and the framework
name).  For each discovered folder, re-reads the Essential and Important columns
from the original Excel file and patches the cached AtomicRequirement JSON files
in-place — no LLM calls needed.

Usage
-----
    python tools/patch_cache_criticality.py              # uses .env by default
    python tools/patch_cache_criticality.py --dry-run    # preview, no writes
    python tools/patch_cache_criticality.py --env other.env
    python tools/patch_cache_criticality.py --essential-col Essential --important-col Important --id-col ID
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _relaunch_in_venv() -> None:
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        return
    if os.path.abspath(sys.executable).lower() == str(venv_python).lower():
        return
    import subprocess
    sys.exit(subprocess.run([str(venv_python)] + sys.argv).returncode)


_relaunch_in_venv()

import pandas as pd
from dotenv import dotenv_values


_CACHE_FILENAMES = (
    "atomic_requirements.json",
    "atomized_requirements.json",
    "atomic_requirements_with_fields.json",
)

_REPORT_FILENAMES = ("processing_report.json", "cache_metadata.json")

_TRUE_TOKENS  = {"true", "vrai", "1", "yes", "oui", "y", "o", "x", "essential", "important"}
_FALSE_TOKENS = {"false", "faux", "0", "no", "non", "n", "", "na", "n/a", "-"}


def _normalize(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def _parse_bool(raw: object, default: bool) -> bool:
    v = _normalize(raw).lower()
    if v in _TRUE_TOKENS:
        return True
    if v in _FALSE_TOKENS:
        return False
    return default


def _read_report(folder: Path) -> dict:
    for name in _REPORT_FILENAMES:
        p = folder / name
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return {}


def _build_criticality_map(
    excel_path: Path,
    sheet_name: str,
    id_col: str,
    essential_col: str,
    important_col: str,
) -> dict[str, dict[str, bool]]:
    """Return {source_id: {essential, important}} mirroring excel_io.py logic."""
    if not excel_path.exists():
        print(f"    [WARN] Excel not found: {excel_path}", flush=True)
        return {}

    df = pd.read_excel(excel_path, sheet_name=sheet_name or 0, dtype=str)
    df.columns = [_normalize(c) for c in df.columns]
    available = list(df.columns)

    for label, col in [("id", id_col), ("essential", essential_col), ("important", important_col)]:
        if col and col not in available:
            print(f"    [WARN] Column '{col}' ({label}) not found. Available: {available}")

    result: dict[str, dict[str, bool]] = {}
    seen_ids: set[str] = set()

    for idx, row in df.iterrows():
        raw_id = _normalize(row.get(id_col, "")) if id_col else ""
        source_id = raw_id or f"row_{idx + 2}"
        if source_id in seen_ids:
            source_id = f"{source_id}__row_{idx + 2}"
        seen_ids.add(source_id)

        essential = _parse_bool(row.get(essential_col, "") if essential_col else "", default=True)
        important = _parse_bool(row.get(important_col, "") if important_col else "", default=False)
        result[source_id] = {"essential": essential, "important": important}

    return result


def _patch_folder(
    folder: Path,
    crit_map: dict[str, dict[str, bool]],
    dry_run: bool,
    docs_cache_dir: Path,
) -> tuple[int, int]:
    """Patch all cache JSON files in one cache folder."""
    total_atoms = 0
    total_patched = 0

    for filename in _CACHE_FILENAMES:
        path = folder / filename
        if not path.exists():
            continue

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"    [SKIP] Cannot read {path.name}: {exc}")
            continue

        if not isinstance(data, list):
            continue

        patched = 0
        for atom in data:
            if not isinstance(atom, dict):
                continue
            pid = str(atom.get("parent_id", "") or "")
            crit = crit_map.get(pid)
            if crit is not None:
                atom["essential"] = crit["essential"]
                atom["important"] = crit["important"]
                patched += 1
            else:
                atom.setdefault("essential", True)
                atom.setdefault("important", False)

        total_atoms += len(data)
        total_patched += patched

        if not dry_run and patched > 0:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        verb = "would patch" if dry_run else "patched"
        rel = path.relative_to(docs_cache_dir)
        print(f"    {verb} {patched:>4}/{len(data):<4} atoms   {rel}")

    return total_atoms, total_patched


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--env",           default=".env",       help="Path to .env file (default: .env)")
    parser.add_argument("--dry-run",       action="store_true",  help="Preview without writing")
    parser.add_argument("--essential-col", default="",           help="Override Essential column name")
    parser.add_argument("--important-col", default="",           help="Override Important column name")
    parser.add_argument("--id-col",        default="",           help="Override ID column name")
    args = parser.parse_args()

    env_path = ROOT / args.env
    if not env_path.exists():
        print(f"[ERROR] .env not found: {env_path}")
        sys.exit(1)

    env = dotenv_values(env_path)
    docs_cache_dir = ROOT / (_normalize(env.get("DOCS_CACHE_DIR", "")) or "cache")

    # Column names: CLI args override .env, which overrides defaults.
    essential_col = args.essential_col or _normalize(env.get("A_ESSENTIAL_COLUMN") or env.get("B_ESSENTIAL_COLUMN") or "Essential")
    important_col = args.important_col or _normalize(env.get("A_IMPORTANT_COLUMN") or env.get("B_IMPORTANT_COLUMN") or "Important")
    id_col        = args.id_col        or _normalize(env.get("A_ID_COLUMN")        or env.get("B_ID_COLUMN")        or "ID")

    print(f"Column config: id={id_col}  essential={essential_col}  important={important_col}")
    if args.dry_run:
        print("(dry-run — no files will be written)")

    if not docs_cache_dir.exists():
        print(f"\n[ERROR] Cache directory not found: {docs_cache_dir}")
        sys.exit(1)

    # ── Autodiscover all cache folders via processing_report.json ────────────
    folders: list[tuple[Path, str, Path]] = []   # (folder, framework_name, excel_path)

    for subdir in sorted(docs_cache_dir.iterdir()):
        if not subdir.is_dir():
            continue
        report = _read_report(subdir)
        if not report:
            continue

        # Prefer 'framework' key; fall back to folder name.
        fw_name = _normalize(report.get("framework") or report.get("framework_name") or subdir.name)
        # Try report source_file first, then reconstruct from file name.
        src = _normalize(report.get("source_file") or "")
        if src:
            excel_path = Path(src)
            if not excel_path.is_absolute():
                excel_path = ROOT / src
        else:
            excel_path = Path("")

        folders.append((subdir, fw_name, excel_path))

    if not folders:
        print(f"\n[ERROR] No cache folders with processing_report.json found in {docs_cache_dir}")
        sys.exit(1)

    # ── Process each discovered folder ───────────────────────────────────────
    total_files = 0
    total_atoms = 0
    total_patched = 0

    for folder, fw_name, excel_path in folders:
        print(f"\n[{folder.name}]  framework={fw_name}")
        print(f"    Excel: {excel_path.name if excel_path.name else '(unknown)'}")

        if not excel_path or not excel_path.exists():
            # Try to find a file with the same stem anywhere under data/
            candidates = list((ROOT / "data").glob(f"{excel_path.stem}*")) if excel_path.stem else []
            if len(candidates) == 1:
                excel_path = candidates[0]
                print(f"    [INFO] Resolved to: {excel_path.name}")
            else:
                print(f"    [SKIP] Excel file not found — cannot patch this folder.")
                continue

        crit_map = _build_criticality_map(excel_path, "", id_col, essential_col, important_col)
        print(f"    Loaded {len(crit_map)} requirements from Excel")

        atoms, patched = _patch_folder(folder, crit_map, args.dry_run, docs_cache_dir)
        total_files += 1
        total_atoms += atoms
        total_patched += patched

    mode = " (dry-run)" if args.dry_run else ""
    print(f"\nDone{mode}: {total_patched}/{total_atoms} atoms updated across {total_files} cache folder(s).")


if __name__ == "__main__":
    main()
