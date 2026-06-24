from __future__ import annotations

import json
from dataclasses import asdict
from collections import defaultdict
from tqdm import tqdm

from .config import AppConfig
from .azure_openai_client import AzureOpenAIClient
from .logging_utils import JsonlRunLogger
from .models import MappingDecision
from .utils import render_prompt, chunks, resolve_language_name
from .matching import sanitize_decision


def _apply_correction(source_id: str, corr: dict, decisions: list[MappingDecision], app_cfg: AppConfig | None = None) -> None:
    target = next((d for d in decisions if d.source_id == source_id), None)
    if target is None:
        return

    for field in ["relation_type", "equivalence_level", "match_type", "gap_type", "justification", "gap", "combine_controls", "recommendation", "mapping_risk", "scoring_rationale"]:
        value = corr.get(field) or corr.get(f"corrected_{field}")
        if value not in (None, ""):
            setattr(target, field, str(value))

    coverage = corr.get("coverage_level", corr.get("corrected_coverage_level"))
    if coverage not in (None, ""):
        try:
            target.coverage_level = int(coverage)
        except Exception:
            pass

    gap_items = corr.get("gap_items") or corr.get("residual_gaps")
    if isinstance(gap_items, list):
        target.gap_items = [x for x in gap_items if isinstance(x, dict)]

    confidence = corr.get("confidence", corr.get("corrected_confidence"))
    if confidence not in (None, ""):
        try:
            target.confidence = float(confidence)
        except Exception:
            pass

    selected = corr.get("selected_candidate_ids") or corr.get("target_ids") or corr.get("corrected_target_ids")
    if isinstance(selected, str):
        selected = [x.strip() for x in selected.split(",") if x.strip()]
    if isinstance(selected, list):
        valid = {c.get("candidate_id"): c for c in target.candidates if isinstance(c, dict)}
        selected = [sid for sid in selected if sid in valid]
        if selected:
            target.selected_candidate_ids = selected
            target.target_ids = selected
            target.target_requirements = [str(valid[sid].get("requirement") or "") for sid in selected]
            parent_ids: list[str] = []
            parent_reqs: list[str] = []
            for sid in selected:
                parent_id = str(valid[sid].get("parent_id") or sid)
                parent_req = str(valid[sid].get("parent_requirement") or valid[sid].get("requirement") or "")
                if parent_id and parent_id not in parent_ids:
                    parent_ids.append(parent_id)
                if parent_req and parent_req not in parent_reqs:
                    parent_reqs.append(parent_req)
            target.target_parent_ids = parent_ids
            target.target_parent_requirements = parent_reqs

    sanitize_decision(target, app_cfg)


def run_final_judge(decisions: list[MappingDecision], app_cfg: AppConfig, llm: AzureOpenAIClient, logger: JsonlRunLogger) -> list[MappingDecision]:
    if not app_cfg.run_final_llm_judge or app_cfg.dry_run_without_llm:
        logger.event("final_judge.skip", reason="disabled_or_dry_run")
        return decisions

    by_category: dict[str, list[MappingDecision]] = defaultdict(list)
    for d in decisions:
        if app_cfg.final_judge_only_ambiguous:
            if d.confidence >= app_cfg.final_judge_confidence_threshold and d.coverage_level > 50:
                continue
        by_category[d.source_category].append(d)

    total_to_review = sum(len(v) for v in by_category.values())
    batch_size = max(1, int(getattr(app_cfg, "final_judge_batch_size", 25) or 25))
    logger.event("final_judge.start", categories=len(by_category), decisions=total_to_review, batch_size=batch_size)
    notes_by_source: dict[str, str] = {}
    review_batches: list[tuple[str, int, list[MappingDecision]]] = []
    for category, items in by_category.items():
        for batch_no, batch in enumerate(chunks(items, batch_size), start=1):
            review_batches.append((category or "Uncategorized", batch_no, batch))

    if review_batches:
        print(f"[3/6] Final judge: reviewing {total_to_review} decision(s) in {len(review_batches)} batch(es)...")
    for category, batch_no, batch in tqdm(review_batches, desc="Final judge", unit="batch"):
        payload = [asdict(d) for d in batch]
        prompt = render_prompt(
            app_cfg.prompt_final_judge,
            category=category,
            output_language=resolve_language_name(app_cfg.output_language),
            mapping_results_json=json.dumps(payload, ensure_ascii=False, indent=2),
        )
        try:
            result = llm.judge_json(prompt)
            summary = str(result.get("summary") or "")
            corrections = result.get("corrections") or []
            for corr in corrections:
                if not isinstance(corr, dict):
                    continue
                source_id = str(corr.get("source_id") or corr.get("id") or "")
                if source_id:
                    notes_by_source[source_id] = json.dumps(corr, ensure_ascii=False)
                    _apply_correction(source_id, corr, decisions, app_cfg)
            logger.event("final_judge.category_batch", category=category, batch=batch_no, items=len(batch), corrections=len(corrections), summary=summary)
        except Exception as exc:
            logger.error("final_judge.category_batch", exc, category=category, batch=batch_no, items=len(batch))

    for d in decisions:
        if d.source_id in notes_by_source:
            d.final_judge_notes = notes_by_source[d.source_id]
    logger.event("final_judge.done", corrections=len(notes_by_source))
    return decisions
