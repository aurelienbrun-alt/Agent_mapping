"""Consolidated framework generation.

Merges two mapped frameworks (A and B) into a single comprehensive framework using
LLM batch consolidation. Requires the A->B mapping results (with b_contribution field
populated by the pairwise match LLM). Optionally uses B->A results for Pass 2.

Pass 1 - A enriched by B:
    For every parent requirement in A, the LLM writes a consolidated requirement that
    captures everything A says, integrates what B adds (b_contribution), and explicitly
    addresses the residual gap so the consolidated text is complete.

Pass 2 - B orphans (requires BIDIRECTIONAL_MAPPING=true):
    B parent requirements with coverage_B->A < CONSOLIDATED_ORPHAN_THRESHOLD are added
    directly as new requirements. Partially-covered B requirements (between threshold
    and 70%) go through a small LLM batch to check for genuinely new obligations.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from tqdm import tqdm

from .config import AppConfig
from .azure_openai_client import AzureOpenAIClient
from .logging_utils import JsonlRunLogger
from .models import MappingDecision
from .utils import render_prompt, chunks, resolve_language_name


@dataclass
class ConsolidatedRequirement:
    consolidated_id: str
    source_id_a: str
    source_ids_b: list[str]
    category: str
    consolidated_text: str
    source_text_a: str
    source_text_b: str
    b_contribution: str
    coverage_a_to_b: int
    gap_a_to_b: str
    origin: str  # "A_enriched" | "B_only" | "B_supplemental"


def _aggregate_parent_groups(decisions: list[MappingDecision]) -> dict[str, dict[str, Any]]:
    """Group atomic decisions by source_parent_id, collecting parent-level info."""
    groups: dict[str, dict[str, Any]] = {}
    for d in decisions:
        pid = d.source_parent_id or d.source_id
        if not pid:
            continue
        if pid not in groups:
            groups[pid] = {
                "parent_id": pid,
                "parent_requirement": d.source_parent_requirement or d.source_requirement,
                "category": d.source_category,
                "target_parent_ids": [],
                "target_parent_requirements": [],
                "b_contributions": [],
                "gaps": [],
                "coverage_sum": 0,
                "coverage_count": 0,
                "parent_gap_summary": "",
            }
        g = groups[pid]

        g["coverage_sum"] += d.coverage_level or 0
        g["coverage_count"] += 1

        for tpid in (d.target_parent_ids or []):
            if tpid and tpid not in g["target_parent_ids"]:
                g["target_parent_ids"].append(tpid)
        for treq in (d.target_parent_requirements or []):
            if treq and treq not in g["target_parent_requirements"]:
                g["target_parent_requirements"].append(treq)

        bc = getattr(d, "b_contribution", "") or ""
        if bc and bc not in g["b_contributions"]:
            g["b_contributions"].append(bc)

        if d.gap and d.gap not in g["gaps"]:
            g["gaps"].append(d.gap)

        if d.parent_gap_summary and not g["parent_gap_summary"]:
            g["parent_gap_summary"] = d.parent_gap_summary

    for g in groups.values():
        if g["coverage_count"] > 0:
            g["avg_coverage"] = round(g["coverage_sum"] / g["coverage_count"])
        else:
            g["avg_coverage"] = 0

    return groups


def _build_pass1_item(g: dict[str, Any]) -> dict[str, Any]:
    best_b_text = " | ".join(g["target_parent_requirements"][:2])
    b_contrib = " ".join(g["b_contributions"][:3])
    gap = g["parent_gap_summary"] or " ".join(g["gaps"][:2])
    return {
        "id": g["parent_id"],
        "source_a_text": g["parent_requirement"],
        "best_b_text": best_b_text,
        "b_contribution": b_contrib,
        "coverage_a_to_b_pct": g["avg_coverage"],
        "gap_a_to_b": gap,
    }


def run_consolidated_framework(
    a_to_b: list[MappingDecision],
    b_to_a: list[MappingDecision] | None,
    app_cfg: AppConfig,
    llm: AzureOpenAIClient,
    logger: JsonlRunLogger,
) -> list[ConsolidatedRequirement]:
    if app_cfg.dry_run_without_llm:
        logger.event("consolidated.skip", reason="dry_run")
        return []

    output_language = resolve_language_name(app_cfg.output_language)
    batch_size = max(1, int(getattr(app_cfg, "consolidated_batch_size", 20) or 20))
    orphan_threshold = int(getattr(app_cfg, "consolidated_orphan_threshold", 40) or 40)
    prompt_batch = getattr(app_cfg, "prompt_consolidated_batch", "") or ""
    prompt_supplement = getattr(app_cfg, "prompt_consolidated_supplement", "") or ""

    a_groups = _aggregate_parent_groups(a_to_b)
    logger.event("consolidated.pass1.start", groups=len(a_groups), batch_size=batch_size)

    consolidated: list[ConsolidatedRequirement] = []
    counter = 1

    group_list = list(a_groups.values())
    print(f"\n[Consolidated] Pass 1: consolidating {len(group_list)} parent requirements (batches of {batch_size})...", flush=True)

    for batch in tqdm(list(chunks(group_list, batch_size)), desc="Consolidating A+B"):
        items = [_build_pass1_item(g) for g in batch]
        result_map: dict[str, dict[str, Any]] = {}

        if prompt_batch:
            try:
                prompt = render_prompt(
                    prompt_batch,
                    output_language=output_language,
                    items_json=json.dumps(items, ensure_ascii=False, indent=2),
                )
                raw = llm.judge_json(prompt)
                for r in (raw.get("results") or []):
                    if isinstance(r, dict) and r.get("id"):
                        result_map[str(r["id"])] = r
            except Exception as exc:
                logger.error("consolidated.pass1.batch", exc, items=len(items))

        for g, item in zip(batch, items):
            pid = g["parent_id"]
            r = result_map.get(pid, {})
            cons_text = str(r.get("consolidated_text") or g["parent_requirement"])
            consolidated.append(ConsolidatedRequirement(
                consolidated_id=f"CONS-{counter:04d}",
                source_id_a=pid,
                source_ids_b=list(g["target_parent_ids"]),
                category=g["category"],
                consolidated_text=cons_text,
                source_text_a=g["parent_requirement"],
                source_text_b=item["best_b_text"],
                b_contribution=item["b_contribution"],
                coverage_a_to_b=g["avg_coverage"],
                gap_a_to_b=item["gap_a_to_b"],
                origin="A_enriched",
            ))
            counter += 1

    logger.event("consolidated.pass1.done", items=len(consolidated))

    # === Pass 2: B requirements not covered by A ===
    if b_to_a is None:
        print("[Consolidated] Pass 2 skipped — BIDIRECTIONAL_MAPPING=false. Enable it to add B-only requirements.", flush=True)
        logger.event("consolidated.pass2.skip", reason="no_b_to_a_mapping")
    else:
        b_groups = _aggregate_parent_groups(b_to_a)
        orphans = [g for g in b_groups.values() if g["avg_coverage"] < orphan_threshold]
        partial_b = [g for g in b_groups.values() if orphan_threshold <= g["avg_coverage"] < 70]

        logger.event("consolidated.pass2.start", orphans=len(orphans), partial=len(partial_b))
        print(f"[Consolidated] Pass 2: {len(orphans)} B-only (cov<{orphan_threshold}%), {len(partial_b)} partial B...", flush=True)

        for g in orphans:
            consolidated.append(ConsolidatedRequirement(
                consolidated_id=f"CONS-{counter:04d}",
                source_id_a="",
                source_ids_b=[g["parent_id"]],
                category=g["category"],
                consolidated_text=g["parent_requirement"],
                source_text_a="",
                source_text_b=g["parent_requirement"],
                b_contribution="",
                coverage_a_to_b=0,
                gap_a_to_b="",
                origin="B_only",
            ))
            counter += 1

        if partial_b and prompt_supplement:
            print(f"[Consolidated] Pass 2b: refining {len(partial_b)} partial B requirements...", flush=True)
            for batch in tqdm(list(chunks(partial_b, batch_size)), desc="B supplemental"):
                items = []
                for g in batch:
                    gap = g["parent_gap_summary"] or " ".join(g["gaps"][:2])
                    items.append({
                        "id": g["parent_id"],
                        "b_text": g["parent_requirement"],
                        "coverage_b_to_a_pct": g["avg_coverage"],
                        "gap_b_to_a": gap,
                    })
                result_map = {}
                try:
                    prompt = render_prompt(
                        prompt_supplement,
                        output_language=output_language,
                        orphan_threshold=str(orphan_threshold),
                        items_json=json.dumps(items, ensure_ascii=False, indent=2),
                    )
                    raw = llm.judge_json(prompt)
                    for r in (raw.get("results") or []):
                        if isinstance(r, dict) and r.get("id"):
                            result_map[str(r["id"])] = r
                except Exception as exc:
                    logger.error("consolidated.pass2b.batch", exc, items=len(items))

                for g in batch:
                    pid = g["parent_id"]
                    r = result_map.get(pid, {})
                    if r.get("already_covered"):
                        continue
                    cons_text = str(r.get("consolidated_text") or "").strip()
                    if not cons_text:
                        continue
                    gap = g["parent_gap_summary"] or " ".join(g["gaps"][:2])
                    consolidated.append(ConsolidatedRequirement(
                        consolidated_id=f"CONS-{counter:04d}",
                        source_id_a="",
                        source_ids_b=[pid],
                        category=g["category"],
                        consolidated_text=cons_text,
                        source_text_a="",
                        source_text_b=g["parent_requirement"],
                        b_contribution="",
                        coverage_a_to_b=g["avg_coverage"],
                        gap_a_to_b=gap,
                        origin="B_supplemental",
                    ))
                    counter += 1

        logger.event("consolidated.pass2.done", b_only=len(orphans))

    logger.event("consolidated.done", total=len(consolidated))
    print(f"[Consolidated] Done: {len(consolidated)} consolidated requirements total.", flush=True)
    return consolidated
