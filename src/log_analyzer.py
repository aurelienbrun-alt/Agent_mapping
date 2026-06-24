from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def _pct(n: int, total: int) -> str:
    return f"{100 * n / total:.1f}%" if total else "0%"


def _stat(values: list[float]) -> str:
    if not values:
        return "n/a"
    avg = sum(values) / len(values)
    return f"avg={avg:.3f}  min={min(values):.3f}  max={max(values):.3f}"


def _stage_timing(events: list[dict[str, Any]]) -> list[tuple[str, float]]:
    """Extract wall-clock duration for each pipeline stage from paired start/done events."""
    from datetime import datetime, timezone
    timestamps: dict[str, float] = {}
    for e in events:
        step = str(e.get("step") or "")
        ts = str(e.get("timestamp") or "")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            timestamps[step] = dt.timestamp()
        except Exception:
            continue

    pairs = [
        ("Full run", "run.start", "run.done"),
        ("Directional mapping", "direction_mapping.start", "direction_mapping.done"),
        ("Final judge", "final_judge.start", "final_judge.done"),
        ("Parent gap synthesis", "parent_gap_synthesis.start", "parent_gap_synthesis.done"),
    ]
    results = []
    for label, start_key, end_key in pairs:
        if start_key in timestamps and end_key and end_key in timestamps:
            delta = timestamps[end_key] - timestamps[start_key]
            if delta >= 0:
                results.append((label, delta))
    return results


def analyze_log_file(jsonl_path: Path, report_dir: Path | None = None) -> Path:
    if not jsonl_path.exists():
        raise FileNotFoundError(jsonl_path)
    events: list[dict[str, Any]] = []
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass

    steps = Counter(e.get("step", "unknown") for e in events)
    statuses = Counter(e.get("status", "unknown") for e in events)
    errors = [e for e in events if e.get("status") == "error"]
    candidates = [e for e in events if e.get("step") == "candidate_generation"]
    by_category = Counter(e.get("category", "") for e in candidates)

    # --- Score distributions ---
    combined_scores = [float(e["best_combined_score"]) for e in candidates if "best_combined_score" in e]
    semantic_scores = [float(e["best_semantic_score"]) for e in candidates if "best_semantic_score" in e]
    ao_scores = [float(e["best_action_object_score"]) for e in candidates if "best_action_object_score" in e]

    # --- Cache statistics ---
    cache_hits = sum(1 for e in candidates if e.get("cache_status") == "hit")
    cache_misses = sum(1 for e in candidates if e.get("cache_status") == "miss")
    obvious_gap_shortcuts = sum(1 for e in candidates if e.get("cache_status") == "obvious_gap_shortcut")
    no_candidates = sum(1 for e in candidates if e.get("cache_status") in {"no_candidate_pool", "no_candidate_after_threshold"})
    total_cand = len(candidates)

    # --- Final judge correction rate ---
    # Use final_judge.done.corrections (unique source_ids corrected) for the headline —
    # batch-level corrections count LLM correction objects which can exceed items per batch.
    judge_done = next((e for e in events if e.get("step") == "final_judge.done"), None)
    judge_batches = [e for e in events if e.get("step") == "final_judge.category_batch"]
    total_corrections = int(judge_done.get("corrections", 0)) if judge_done else sum(int(e.get("corrections", 0)) for e in judge_batches)
    total_reviewed = sum(int(e.get("items", 0)) for e in judge_batches)

    # --- Combined score distribution buckets ---
    buckets = {">=0.6": 0, "0.5-0.6": 0, "0.4-0.5": 0, "<0.4": 0}
    for s in combined_scores:
        if s >= 0.6:
            buckets[">=0.6"] += 1
        elif s >= 0.5:
            buckets["0.5-0.6"] += 1
        elif s >= 0.4:
            buckets["0.4-0.5"] += 1
        else:
            buckets["<0.4"] += 1

    # --- action_object empty rate ---
    ao_zero = sum(1 for s in ao_scores if s == 0.0)

    # --- Timing ---
    timing = _stage_timing(events)

    # --- LLM pool sizes ---
    llm_candidate_sizes = [int(e["llm_candidates"]) for e in candidates if "llm_candidates" in e]

    report_dir = report_dir or jsonl_path.parent
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"log_analysis_{jsonl_path.stem}.md"

    lines = [
        f"# Log analysis — {jsonl_path.stem}",
        "",
        "## Summary",
        f"- Total events: {len(events)}",
        f"- Errors: {len(errors)}",
        f"- Candidate generation events: {total_cand}",
        "",
        "## Score distributions (best candidate per source atom)",
        f"- Combined score:       {_stat(combined_scores)}",
        f"- Semantic score:       {_stat(semantic_scores)}",
        f"- Action/object score:  {_stat(ao_scores)}",
        "",
        "## Combined score buckets",
    ]
    for bucket, count in buckets.items():
        lines.append(f"  - {bucket}: {count} ({_pct(count, total_cand)})")

    lines += [
        "",
        "## Action/object score health",
        f"- Score = 0.0 (fields not extracted or no family match): {ao_zero}/{total_cand} ({_pct(ao_zero, total_cand)})",
        f"  → High rate means action/object fields are empty in source or target atoms.",
        "",
        "## Cache statistics",
        f"- LLM call (miss):      {cache_misses} ({_pct(cache_misses, total_cand)})",
        f"- Cache hit:            {cache_hits} ({_pct(cache_hits, total_cand)})",
        f"- Obvious gap shortcut: {obvious_gap_shortcuts} ({_pct(obvious_gap_shortcuts, total_cand)})",
        f"- No candidate:         {no_candidates} ({_pct(no_candidates, total_cand)})",
        "",
        "## LLM candidate pool sizes",
        f"- {_stat([float(x) for x in llm_candidate_sizes])}",
        "",
        "## Final judge corrections",
    ]
    if total_reviewed:
        rate = 100 * total_corrections / total_reviewed
        alert = "  ⚠ HIGH — pairwise prompt may be systematically over-conservative." if rate > 35 else ""
        lines.append(f"- Corrected mappings: {total_corrections}/{total_reviewed} ({rate:.1f}%){alert}")
        lines.append(f"  (correction count = unique source_ids modified by final judge)")
    else:
        lines.append("- No final judge data.")
    for e in judge_batches:
        batch_corr = int(e.get("corrections", 0))
        batch_items = int(e.get("items", 0))
        note = " (correction events, may exceed items)" if batch_corr > batch_items else ""
        lines.append(f"  - [{e.get('category', '?')}] batch {e.get('batch')}: {batch_corr} correction events / {batch_items} items{note}")

    if timing:
        lines += ["", "## Stage timing"]
        for label, secs in timing:
            m, s = divmod(int(secs), 60)
            lines.append(f"- {label}: {m}m {s}s")

    lines += ["", "## Event counts"]
    for step, count in steps.most_common():
        lines.append(f"- {step}: {count}")

    lines += ["", "## Candidate generation by category"]
    for category, count in by_category.most_common():
        lines.append(f"- {category or '(empty)'}: {count}")

    if errors:
        lines += ["", "## Errors"]
        for e in errors:
            lines.append(f"- {e.get('timestamp')} — {e.get('step')}: {e.get('error')}")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path
