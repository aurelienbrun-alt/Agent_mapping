"""Score agent/consultant agreement from a comparison workbook.

Usage:
    python evaluate_mapping.py "C:/path/to/Comparaison.xlsx"
    python evaluate_mapping.py "C:/path/to/Comparaison.xlsx" "output/mapping_....xlsx"

One-argument mode: the workbook must contain one sheet whose name contains
"Agent" (the parent sheet exported from the mapper output: header row with
'Source control ID' and 'Coverage level') and one sheet whose name contains
"Consultant" (free-form rows where one cell holds "<ID>: requirement text" and
another a coverage label such as Covered / Partially covered / Not covered).

Two-argument mode: the consultant sheet is read from the first workbook and the
agent side is read directly from a mapper OUTPUT workbook (its parent mapping
sheet, e.g. 'Cyfun 2025 -> France 2.3'), so runs can be scored without manually
pasting the Agent sheet into the comparison file.

Prints a per-requirement diff table plus agreement metrics, so every run can be
scored against the consultant gold standard instead of eyeballing Excel.
"""
from __future__ import annotations

import re
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd

ID_RE = re.compile(r"([A-Z]{2}\.[A-Z]{2}-\d+\.\d+)")
BUCKETS = (0, 25, 50, 75, 100)

# Order matters: "not covered" must match before "covered".
LABELS = [
    ("not covered", 0), ("non couvert", 0),
    ("indirect", 25),
    ("partial", 50), ("partiel", 50),
    ("largely", 75), ("largement", 75), ("mostly", 75),
    ("fully covered", 100), ("exact", 100), ("covered", 100), ("couvert", 100),
]


def label_to_bucket(value) -> int | None:
    text = str(value or "").strip().lower()
    if not text or len(text) > 40:
        return None
    for key, bucket in LABELS:
        if key in text:
            return bucket
    return None


def to_bucket(value) -> int | None:
    try:
        cov = float(value)
    except Exception:
        return None
    cov = max(0.0, min(100.0, cov))
    return int(min(BUCKETS, key=lambda b: (abs(b - cov), -b)))


def read_workbook(path: Path) -> dict[str, pd.DataFrame]:
    """Read all sheets, copying to a temp file first if Excel holds a lock."""
    try:
        return pd.read_excel(path, sheet_name=None, header=None)
    except PermissionError:
        tmp = Path(tempfile.gettempdir()) / f"_eval_{path.name}"
        shutil.copy(path, tmp)
        try:
            return pd.read_excel(tmp, sheet_name=None, header=None)
        finally:
            tmp.unlink(missing_ok=True)


def parse_agent(raw: pd.DataFrame) -> dict[str, int]:
    header_idx = None
    for i in range(min(10, len(raw))):
        if raw.iloc[i].astype(str).str.contains("Source control ID").any():
            header_idx = i
            break
    if header_idx is None:
        raise SystemExit("Agent sheet: header row with 'Source control ID' not found.")
    df = raw.iloc[header_idx + 1:].copy()
    df.columns = raw.iloc[header_idx]
    result: dict[str, int] = {}
    for _, row in df.iterrows():
        m = ID_RE.search(str(row.get("Source control ID") or ""))
        bucket = to_bucket(row.get("Coverage level"))
        if m and bucket is not None:
            result[m.group(1)] = bucket
    return result


def parse_consultant(raw: pd.DataFrame) -> dict[str, int]:
    """Free-form rows: one cell contains '<ID>: text', another a coverage label.

    Duplicate IDs (the consultant sometimes splits one control over two rows)
    keep the highest coverage found.
    """
    result: dict[str, int] = {}
    for _, row in raw.iterrows():
        row_id, bucket = None, None
        for cell in row:
            if row_id is None:
                m = ID_RE.search(str(cell or ""))
                if m:
                    row_id = m.group(1)
            if bucket is None:
                bucket = label_to_bucket(cell)
        if row_id and bucket is not None:
            result[row_id] = max(result.get(row_id, 0), bucket)
    return result


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    path = Path(sys.argv[1])
    sheets = read_workbook(path)

    agent_df = consultant_df = None
    for name, df in sheets.items():
        low = name.strip().lower()
        if "agent" in low:
            agent_df = df
        elif "consultant" in low:
            consultant_df = df

    if len(sys.argv) >= 3:
        # Two-argument mode: agent side comes from a mapper output workbook's
        # parent sheet (name contains '->' and is not the atomic detail sheet).
        out_sheets = read_workbook(Path(sys.argv[2]))
        agent_df = None
        for name, df in out_sheets.items():
            if "->" in name and "atomic" not in name.strip().lower():
                agent_df = df
                break
        if agent_df is None:
            raise SystemExit(f"No parent mapping sheet (name containing '->') in {sys.argv[2]}: {list(out_sheets)}")

    if agent_df is None or consultant_df is None:
        raise SystemExit(f"Sheets found: {list(sheets)} — need one 'Agent' and one 'Consultant' sheet.")

    agent = parse_agent(agent_df)
    consultant = parse_consultant(consultant_df)
    common = sorted(set(agent) & set(consultant))
    if not common:
        raise SystemExit("No common requirement IDs between the two sheets.")

    print(f"{'ID':<14} {'Agent':>6} {'Consultant':>11} {'Diff':>6}")
    print("-" * 41)
    exact = within = over = under = 0
    signed_sum = 0
    for rid in common:
        a, c = agent[rid], consultant[rid]
        diff = a - c
        signed_sum += diff
        exact += diff == 0
        within += abs(diff) <= 25
        over += diff > 0
        under += diff < 0
        flag = "" if diff == 0 else ("  OVER" if diff > 0 else "  UNDER")
        print(f"{rid:<14} {a:>6} {c:>11} {diff:>+6}{flag}")

    n = len(common)
    print("-" * 41)
    print(f"Matched requirements : {n} (agent={len(agent)}, consultant={len(consultant)})")
    print(f"Exact bucket match   : {exact}/{n} ({exact / n * 100:.0f}%)")
    print(f"Within one bucket    : {within}/{n} ({within / n * 100:.0f}%)")
    print(f"Direction            : {over} over-credited, {under} under-credited")
    print(f"Mean signed error    : {signed_sum / n:+.1f} points (positive = agent too generous)")
    only_a = sorted(set(agent) - set(consultant))
    only_c = sorted(set(consultant) - set(agent))
    if only_a:
        print(f"Agent-only IDs       : {', '.join(only_a)}")
    if only_c:
        print(f"Consultant-only IDs  : {', '.join(only_c)}")


if __name__ == "__main__":
    main()
