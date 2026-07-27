from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
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

    # Snapshot the pairwise coverage before the final judge overwrites it, so the
    # magnitude of any overturn can be used as a reliability signal downstream.
    if getattr(target, "pre_final_judge_coverage", None) is None:
        try:
            target.pre_final_judge_coverage = int(target.coverage_level)
        except Exception:
            target.pre_final_judge_coverage = None

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

    # The final judge is the last arbiter: its corrected coverage must not be
    # silently re-capped by the deterministic object/action score gate (same
    # anti-pattern as the removed score floor / rescue-at-80).
    sanitize_decision(target, app_cfg, skip_object_action_cap=True)


# Top retrieval candidates shown to the final judge so it can re-select a more
# specific target (selected_candidate_ids corrections are validated against the
# full candidate list, so the judge may only pick ids it was actually shown).
FINAL_JUDGE_CANDIDATES_SHOWN = 10
_CANDIDATE_TEXT_MAX_CHARS = 240


def _compact_candidates(d: MappingDecision) -> list[dict]:
    cands = [c for c in (d.candidates or []) if isinstance(c, dict)]
    def _combined(c: dict) -> float:
        scores = c.get("scores") if isinstance(c.get("scores"), dict) else {}
        try:
            return float(scores.get("combined", c.get("combined_score", 0)) or 0)
        except Exception:
            return 0.0
    cands = sorted(cands, key=_combined, reverse=True)[:FINAL_JUDGE_CANDIDATES_SHOWN]
    out = []
    for c in cands:
        out.append({
            "candidate_id": c.get("candidate_id"),
            "parent_id": c.get("parent_id"),
            "requirement": str(c.get("requirement") or "")[:_CANDIDATE_TEXT_MAX_CHARS],
        })
    return out


def _judge_payload(d: MappingDecision) -> dict:
    """Payload pour le final judge.

    `retrieval_candidates` expose une version compacte (id + parent + extrait)
    des meilleurs candidats retrouves, pour que le juge final puisse corriger la
    SELECTION (choisir un controle plus specifique) et pas seulement le score.
    Le payload complet des candidats (scores, champs structures) reste exclu
    pour contenir la taille du prompt.
    """
    return {
        "source_id": d.source_id,
        "source_requirement": d.source_requirement,
        "source_category": d.source_category,
        "target_ids": d.target_ids,
        "target_requirements": d.target_requirements,
        "retrieval_candidates": _compact_candidates(d),
        "relation_type": d.relation_type,
        "equivalence_level": d.equivalence_level,
        "coverage_level": d.coverage_level,
        "match_type": d.match_type,
        "gap_type": d.gap_type,
        "gap": d.gap,
        "gap_items": d.gap_items,
        "confidence": d.confidence,
        "mapping_risk": d.mapping_risk,
    }


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

    # Each batch is an independent LLM call, so run them in parallel. Only the LLM
    # request happens on worker threads; corrections mutate the shared `decisions`
    # list and are therefore applied sequentially on the main thread below.
    max_workers = max(1, int(getattr(app_cfg, "final_judge_max_concurrent_calls", 0) or app_cfg.max_concurrent_llm_calls or 1))

    def _review(item: tuple[str, int, list[MappingDecision]]) -> tuple[str, int, list, str, Exception | None]:
        category, batch_no, batch = item
        payload = [_judge_payload(d) for d in batch]
        prompt = render_prompt(
            app_cfg.prompt_final_judge,
            category=category,
            output_language=resolve_language_name(app_cfg.output_language),
            mapping_results_json=json.dumps(payload, ensure_ascii=False, indent=2),
        )
        try:
            result = llm.final_judge_json(prompt)
            return category, batch_no, (result.get("corrections") or []), str(result.get("summary") or ""), None
        except Exception as exc:  # surfaced on the main thread below
            return category, batch_no, [], "", exc

    failed_batches: list[str] = []

    def _handle(category: str, batch_no: int, batch_len: int, corrections: list, summary: str, exc: Exception | None) -> None:
        if exc is not None:
            failed_batches.append(f"{type(exc).__name__}: {str(exc)[:200]}")
            logger.error("final_judge.category_batch", exc, category=category, batch=batch_no, items=batch_len)
            return
        for corr in corrections:
            if not isinstance(corr, dict):
                continue
            source_id = str(corr.get("source_id") or corr.get("id") or "")
            if source_id:
                notes_by_source[source_id] = json.dumps(corr, ensure_ascii=False)
                _apply_correction(source_id, corr, decisions, app_cfg)
        logger.event("final_judge.category_batch", category=category, batch=batch_no, items=batch_len, corrections=len(corrections), summary=summary)

    batch_len_by_key = {(c, n): len(b) for c, n, b in review_batches}
    if max_workers <= 1:
        for item in tqdm(review_batches, desc="Final judge", unit="batch"):
            category, batch_no, corrections, summary, exc = _review(item)
            _handle(category, batch_no, batch_len_by_key[(category, batch_no)], corrections, summary, exc)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_review, item) for item in review_batches]
            for future in tqdm(as_completed(futures), total=len(futures), desc="Final judge", unit="batch"):
                category, batch_no, corrections, summary, exc = future.result()
                _handle(category, batch_no, batch_len_by_key[(category, batch_no)], corrections, summary, exc)

    for d in decisions:
        if d.source_id in notes_by_source:
            d.final_judge_notes = notes_by_source[d.source_id]
    # A failing final judge must never look like a successful run: surface it
    # loudly (same lesson as the silent pairwise fallbacks).
    if failed_batches:
        from collections import Counter
        error_counts = Counter(msg.split(":")[0] for msg in failed_batches)
        print(
            f"[WARNING] {len(failed_batches)}/{len(review_batches)} final-judge batch(es) FAILED - "
            f"their items received NO final-judge review: {dict(error_counts)} - e.g. {failed_batches[0]}",
            flush=True,
        )
        logger.event("final_judge.batch_failures", failed=len(failed_batches), total=len(review_batches), first_error=failed_batches[0])
    logger.event("final_judge.done", corrections=len(notes_by_source))
    return decisions
