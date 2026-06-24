from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import numpy as np
from tqdm import tqdm

from .config import AppConfig
from .azure_openai_client import AzureOpenAIClient
from .logging_utils import JsonlRunLogger
from .models import AtomicRequirement, CandidateScore, MappingDecision
from .utils import normalize_category, tokenize, render_prompt, resolve_language_name
from .mapping_cache import MappingDecisionCache, build_mapping_cache_key


SUPPORTED_MATCH_SCOPES = {"same_enisa_category", "same_category", "soft_enisa", "soft_enisa_category", "all"}
SCORE_LEVELS = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

GAP_TYPES = {
    "none",
    "true_gap",
    "partial_gap",
    "implementation_detail_gap",
    "indirect_support_gap",
    "conflict_gap",
}



def run_directional_mapping(
    source_atoms: list[AtomicRequirement],
    target_atoms: list[AtomicRequirement],
    *,
    direction: str,
    app_cfg: AppConfig,
    llm: AzureOpenAIClient,
    logger: JsonlRunLogger,
    guideline_index=None,
) -> list[MappingDecision]:
    if app_cfg.match_scope not in SUPPORTED_MATCH_SCOPES:
        raise ValueError("Unsupported MATCH_SCOPE. Use soft_enisa, same_enisa_category, same_category or all.")

    target_by_id = {a.atomic_id: a for a in target_atoms}
    indexes = build_target_indexes(target_atoms, app_cfg)
    cache = MappingDecisionCache(
        app_cfg.docs_cache_dir / app_cfg.mapping_decision_cache_file,
        enabled=app_cfg.enable_mapping_decision_cache and not app_cfg.dry_run_without_llm,
    )

    max_workers = max(1, int(getattr(app_cfg, "max_concurrent_llm_calls", 1) or 1))
    if app_cfg.dry_run_without_llm or not app_cfg.use_llm_pairwise_evaluation:
        max_workers = 1

    logger.event(
        "direction_mapping.start",
        direction=direction,
        source_atoms=len(source_atoms),
        target_atoms=len(target_atoms),
        max_concurrent_llm_calls=max_workers,
        mapping_cache_enabled=cache.enabled,
        llm_top_k_candidates=app_cfg.llm_top_k_candidates,
    )

    decisions: list[MappingDecision | None] = [None] * len(source_atoms)

    def process_one(index: int, source: AtomicRequirement) -> tuple[int, MappingDecision, dict[str, Any]]:
        candidates_pool, scope_used, scope_key = select_candidate_pool(source, indexes, app_cfg)
        log_data: dict[str, Any] = {
            "direction": direction,
            "source_id": source.atomic_id,
            "category": source.category,
            "scope_used": scope_used,
            "scope_key": scope_key,
            "pool_size": len(candidates_pool),
            "cache_status": "not_checked",
        }
        if not candidates_pool:
            decision = gap_decision(direction, source, f"No candidate for scope {scope_used}: {scope_key}")
            log_data.update(candidates=0, llm_candidates=0, best_combined_score=0.0, cache_status="no_candidate_pool")
            return index, decision, log_data

        candidate_scores = generate_candidates(source, candidates_pool, app_cfg)
        candidate_scores = [s for s in candidate_scores if s.combined_score >= app_cfg.min_candidate_combined_score]
        # LLM limit is independent of the scoring pool size: the LLM may see more
        # candidates than top_k_candidates when llm_top_k_candidates > top_k_candidates.
        llm_limit = app_cfg.llm_top_k_candidates if app_cfg.llm_top_k_candidates and app_cfg.llm_top_k_candidates > 0 else app_cfg.top_k_candidates
        llm_candidate_scores = candidate_scores[:llm_limit]
        # Scoring pool (stats, cache key) stays bounded by top_k_candidates.
        candidate_scores = candidate_scores[: app_cfg.top_k_candidates]
        best = candidate_scores[0] if candidate_scores else None
        log_data.update(
            candidates=len(candidate_scores),
            llm_candidates=len(llm_candidate_scores),
            best_combined_score=round(best.combined_score, 4) if best else 0.0,
            best_semantic_score=round(best.semantic_score, 4) if best else 0.0,
            best_action_object_score=round(best.action_object_score, 4) if best else 0.0,
        )

        if not candidate_scores:
            decision = gap_decision(direction, source, "No candidate passed the combined score threshold")
            log_data["cache_status"] = "no_candidate_after_threshold"
            return index, decision, log_data

        if is_obvious_gap(candidate_scores[0], app_cfg):
            payload = build_candidates_payload(llm_candidate_scores, target_by_id)
            decision = gap_decision(direction, source, "Obvious Gap shortcut: best retrieval scores are below safe thresholds.", payload)
            log_data["cache_status"] = "obvious_gap_shortcut"
            return index, decision, log_data

        cache_key = build_mapping_cache_key(
            app_cfg=app_cfg,
            direction=direction,
            source=source,
            candidate_scores=llm_candidate_scores,
            target_by_id=target_by_id,
        )
        cached = cache.get(cache_key)
        if cached is not None:
            cached = sanitize_decision(cached, app_cfg)
            log_data["cache_status"] = "hit"
            return index, cached, log_data

        log_data["cache_status"] = "miss"
        guideline_passages: list[str] = []
        if guideline_index is not None and guideline_index.loaded and getattr(source, "embedding", None):
            guideline_passages = guideline_index.retrieve(source.embedding, top_k=app_cfg.guideline_top_k)
        decision = evaluate_candidates_with_repeat(source, llm_candidate_scores, target_by_id, direction, app_cfg, llm, scope_used, guideline_passages=guideline_passages)
        cache.set(cache_key, decision)
        return index, decision, log_data

    if max_workers <= 1:
        for idx, source in enumerate(tqdm(source_atoms, desc=f"Mapping {direction}")):
            i, decision, log_data = process_one(idx, source)
            decisions[i] = decision
            logger.event("candidate_generation", **log_data)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(process_one, idx, source) for idx, source in enumerate(source_atoms)]
            for future in tqdm(as_completed(futures), total=len(futures), desc=f"Mapping {direction}"):
                i, decision, log_data = future.result()
                decisions[i] = decision
                logger.event("candidate_generation", **log_data)

    final_decisions = [d for d in decisions if d is not None]
    logger.event("direction_mapping.done", direction=direction, decisions=len(final_decisions))
    return final_decisions


def evaluate_candidates_with_repeat(
    source: AtomicRequirement,
    candidate_scores: list[CandidateScore],
    target_by_id: dict[str, AtomicRequirement],
    direction: str,
    app_cfg: AppConfig,
    llm: AzureOpenAIClient,
    scope_used: str,
    guideline_passages: list[str] | None = None,
) -> MappingDecision:
    decision = evaluate_candidates(source, candidate_scores, target_by_id, direction, app_cfg, llm, scope_used, guideline_passages=guideline_passages)
    if app_cfg.llm_repeat_on_low_confidence and decision.confidence < app_cfg.llm_confidence_threshold and not app_cfg.dry_run_without_llm:
        repeated = evaluate_candidates(source, candidate_scores, target_by_id, direction, app_cfg, llm, scope_used, guideline_passages=guideline_passages)
        if repeated.confidence >= decision.confidence:
            return repeated
    return decision


def is_obvious_gap(best: CandidateScore, app_cfg: AppConfig) -> bool:
    if not getattr(app_cfg, "enable_obvious_gap_shortcut", False):
        return False
    return (
        best.combined_score < app_cfg.obvious_gap_combined_threshold
        and best.semantic_score < app_cfg.obvious_gap_semantic_threshold
        and best.action_object_score < app_cfg.obvious_gap_action_object_threshold
    )

def build_target_indexes(target_atoms: list[AtomicRequirement], app_cfg: AppConfig) -> dict[str, Any]:
    by_category: dict[str, list[AtomicRequirement]] = defaultdict(list)
    for atom in target_atoms:
        for cat_key in atom_category_keys(atom, app_cfg):
            by_category[cat_key].append(atom)
    return {"all": target_atoms, "by_category": by_category}


def select_candidate_pool(
    source: AtomicRequirement,
    indexes: dict[str, Any],
    app_cfg: AppConfig,
) -> tuple[list[AtomicRequirement], str, str]:
    if app_cfg.match_scope in {"all", "soft_enisa", "soft_enisa_category"}:
        # Robust mode: categories are advisory priors, never hard filters.
        return indexes["all"], app_cfg.match_scope, "global_pool_with_category_prior"
    cat_keys = atom_category_keys(source, app_cfg)
    if cat_keys:
        pool: list[AtomicRequirement] = []
        seen: set[str] = set()
        for cat_key in cat_keys:
            for atom in indexes["by_category"].get(cat_key, []):
                if atom.atomic_id not in seen:
                    pool.append(atom)
                    seen.add(atom.atomic_id)
        return pool, "enisa_category", ";".join(cat_keys)
    return indexes["all"], "all", "no_category"


def match_key(value: str, app_cfg: AppConfig) -> str:
    return normalize_category(
        value,
        case_sensitive=app_cfg.category_case_sensitive,
        trim_spaces=app_cfg.category_trim_spaces,
    )


def atom_category_keys(atom: AtomicRequirement, app_cfg: AppConfig) -> list[str]:
    keys: list[str] = []
    for value in [getattr(atom, "primary_category", "") or atom.category, atom.category]:
        key = match_key(value, app_cfg)
        if key and key not in keys:
            keys.append(key)
    if getattr(app_cfg, "enable_secondary_category_matching", True):
        for value in getattr(atom, "secondary_categories", []) or []:
            key = match_key(str(value), app_cfg)
            if key and key not in keys:
                keys.append(key)
    return keys


def category_prior_score(source: AtomicRequirement, candidate: AtomicRequirement, app_cfg: AppConfig) -> float:
    """Category is an advisory prior, never a penalty.

    A bad ENISA attribution must not be able to break a run. The prior is
    therefore confidence-weighted and intentionally small; it can help a good
    same-category candidate rise in the ranking, but it cannot exclude global
    candidates found through semantic/structured similarity.
    """
    src_primary = match_key(getattr(source, "primary_category", "") or source.category, app_cfg)
    tgt_primary = match_key(getattr(candidate, "primary_category", "") or candidate.category, app_cfg)
    src_secondary = {match_key(str(v), app_cfg) for v in (getattr(source, "secondary_categories", []) or [])}
    tgt_secondary = {match_key(str(v), app_cfg) for v in (getattr(candidate, "secondary_categories", []) or [])}
    src_secondary.discard("")
    tgt_secondary.discard("")

    raw = 0.0
    if src_primary and src_primary == tgt_primary:
        raw = 1.0
    elif src_primary and src_primary in tgt_secondary:
        raw = 0.70
    elif tgt_primary and tgt_primary in src_secondary:
        raw = 0.70
    elif src_secondary & tgt_secondary:
        raw = 0.45

    src_conf = _category_confidence(source)
    tgt_conf = _category_confidence(candidate)
    confidence_factor = max(0.15, min(src_conf, tgt_conf))
    # If either category is explicitly low confidence, never give a strong prior.
    if _category_is_low_confidence(source) or _category_is_low_confidence(candidate):
        confidence_factor = min(confidence_factor, 0.30)
    return max(0.0, min(1.0, raw * confidence_factor))


def _category_confidence(atom: AtomicRequirement) -> float:
    for attr in ["category_confidence", "category_harmonization_confidence"]:
        try:
            value = float(getattr(atom, attr, 0.0) or 0.0)
            if value > 0:
                return max(0.0, min(1.0, value))
        except Exception:
            pass
    return 0.50


def _category_is_low_confidence(atom: AtomicRequirement) -> bool:
    status = str(getattr(atom, "category_status", "") or "").casefold()
    if "low" in status or "review" in status:
        return True
    return _category_confidence(atom) < 0.60


def generate_candidates(source: AtomicRequirement, candidates: list[AtomicRequirement], app_cfg: AppConfig) -> list[CandidateScore]:
    score_map = {c.atomic_id: CandidateScore(candidate_id=c.atomic_id) for c in candidates}
    rankings: dict[str, list[str]] = {}

    if app_cfg.use_semantic_matching:
        semantic = [(c.atomic_id, cosine(source.embedding, c.embedding)) for c in candidates]
        semantic.sort(key=lambda x: x[1], reverse=True)
        rankings["semantic"] = [cid for cid, _ in semantic]
        for cid, score in semantic:
            score_map[cid].semantic_score = max(0.0, score)

    if app_cfg.use_keyword_matching:
        keyword_scores = bm25_rank(source, candidates)
        rankings["keyword"] = [cid for cid, _ in keyword_scores]
        for cid, score in keyword_scores:
            score_map[cid].keyword_score = score

    if app_cfg.use_structured_field_matching:
        structured = [(c.atomic_id, structured_similarity(source, c)) for c in candidates]
        action_object = [(c.atomic_id, action_object_similarity(source, c)) for c in candidates]
        control_type = [(c.atomic_id, control_type_similarity(source, c)) for c in candidates]
        structured.sort(key=lambda x: x[1], reverse=True)
        action_object.sort(key=lambda x: x[1], reverse=True)
        control_type.sort(key=lambda x: x[1], reverse=True)
        rankings["structured"] = [cid for cid, _ in structured]
        rankings["action_object"] = [cid for cid, _ in action_object]
        for cid, score in structured:
            score_map[cid].structured_score = score
        for cid, score in action_object:
            score_map[cid].action_object_score = score
        for cid, score in control_type:
            score_map[cid].control_type_score = score

    if app_cfg.use_rrf:
        weights = {
            "semantic": app_cfg.weight_semantic,
            "keyword": app_cfg.weight_keyword,
            "structured": app_cfg.weight_structured,
            "action_object": app_cfg.weight_action_object,
        }
        rrf = reciprocal_rank_fusion(rankings, k=app_cfg.rrf_k, weights=weights)
        for rank, (cid, score) in enumerate(rrf, start=1):
            score_map[cid].rrf_score = score
            score_map[cid].final_rank = rank

    for c in candidates:
        s = score_map[c.atomic_id]
        s.category_score = category_prior_score(source, c, app_cfg)
        base_score = (
            app_cfg.weight_semantic * s.semantic_score
            + app_cfg.weight_keyword * s.keyword_score
            + app_cfg.weight_structured * s.structured_score
            + app_cfg.weight_action_object * s.action_object_score
            + app_cfg.weight_control_type * s.control_type_score
        ) / max(
            app_cfg.weight_semantic
            + app_cfg.weight_keyword
            + app_cfg.weight_structured
            + app_cfg.weight_action_object
            + app_cfg.weight_control_type,
            0.0001,
        )
        # Category is a pure boost. Bad categories never reduce the base score.
        s.combined_score = min(1.0, base_score + app_cfg.weight_category_prior * s.category_score)
        if app_cfg.enforce_object_action_gate and s.action_object_score < app_cfg.object_action_cap_75_threshold:
            s.hard_gate = "low_action_object_alignment_score_cap"

    ordered = sorted(score_map.values(), key=lambda x: (x.combined_score, x.rrf_score), reverse=True)
    for rank, s in enumerate(ordered, start=1):
        s.final_rank = rank
    return ordered


def build_candidates_payload(candidate_scores: list[CandidateScore], target_by_id: dict[str, AtomicRequirement]) -> list[dict[str, Any]]:
    candidates_payload: list[dict[str, Any]] = []
    for s in candidate_scores:
        target = target_by_id[s.candidate_id]
        candidates_payload.append({
            "candidate_id": target.atomic_id,
            "parent_id": target.parent_id,
            "parent_requirement": target.parent_requirement,
            "category": target.category,
            "secondary_categories": getattr(target, "secondary_categories", []),
            "category_confidence": getattr(target, "category_confidence", 0.0),
            "requirement": target.atomic_requirement,
            "fields": target.fields,
            "semantic_score": round(s.semantic_score, 4),
            "keyword_score": round(s.keyword_score, 4),
            "structured_score": round(s.structured_score, 4),
            "action_object_score": round(s.action_object_score, 4),
            "control_type_score": round(s.control_type_score, 4),
            "category_prior_score": round(s.category_score, 4),
            "combined_score": round(s.combined_score, 4),
            "hard_gate": s.hard_gate,
            "rank": s.final_rank,
        })
    return candidates_payload


def evaluate_candidates(
    source: AtomicRequirement,
    candidate_scores: list[CandidateScore],
    target_by_id: dict[str, AtomicRequirement],
    direction: str,
    app_cfg: AppConfig,
    llm: AzureOpenAIClient,
    scope_used: str,
    guideline_passages: list[str] | None = None,
) -> MappingDecision:
    candidates_payload = build_candidates_payload(candidate_scores, target_by_id)

    if app_cfg.dry_run_without_llm or not app_cfg.use_llm_pairwise_evaluation:
        return heuristic_decision(direction, source, candidates_payload, target_by_id, app_cfg)

    source_req_dict: dict[str, Any] = {
        "atomic_id": source.atomic_id,
        "parent_id": source.parent_id,
        "parent_requirement": source.parent_requirement,
        "requirement": source.atomic_requirement,
        "category": source.category,
        "secondary_categories": getattr(source, "secondary_categories", []),
        "category_confidence": getattr(source, "category_confidence", 0.0),
        "category_status": getattr(source, "category_status", ""),
        "category_note": "ENISA categories are advisory retrieval signals only and may be wrong. Do not rely on category alone.",
        "fields": source.fields,
    }
    if guideline_passages:
        source_req_dict["guideline_context"] = (
            "The following passages from the source regulation's official guidelines provide "
            "additional context that may fill implicit gaps in the requirement text above. "
            "Use them to inform your coverage assessment:\n\n"
            + "\n\n---\n\n".join(guideline_passages)
        )

    prompt = render_prompt(
        app_cfg.prompt_pairwise_match,
        self_review_rounds=app_cfg.llm_self_review_rounds if app_cfg.llm_self_review else 1,
        output_language=resolve_language_name(app_cfg.output_language),
        source_requirement=json.dumps(source_req_dict, ensure_ascii=False),
        source_category=source.category,
        match_scope_used=scope_used,
        candidates_json=json.dumps(candidates_payload, ensure_ascii=False, indent=2),
    )
    try:
        result = llm.judge_json(prompt)
        decision = decision_from_llm_result(direction, source, result, candidates_payload, target_by_id)
        return sanitize_decision(decision, app_cfg)
    except Exception:
        decision = heuristic_decision(direction, source, candidates_payload, target_by_id, app_cfg)
        decision.justification = "LLM evaluation failed; deterministic heuristic fallback used. Manual review required."
        decision.recommendation = "Manual review required. Technical API details are available in logs."
        if decision.coverage_level > 50:
            decision.coverage_level = 50
            decision.equivalence_level = "Partial"
            decision.confidence = min(decision.confidence, 0.45)
        return sanitize_decision(decision, app_cfg)


def _source_parent_kwargs(source: AtomicRequirement) -> dict[str, Any]:
    return {
        "source_parent_id": source.parent_id,
        "source_parent_requirement": source.parent_requirement,
        "source_title": source.title,
    }


def _target_parent_ids(targets: list[AtomicRequirement]) -> list[str]:
    seen: list[str] = []
    for target in targets:
        value = target.parent_id or target.atomic_id
        if value and value not in seen:
            seen.append(value)
    return seen


def _target_parent_requirements(targets: list[AtomicRequirement]) -> list[str]:
    seen: list[str] = []
    for target in targets:
        value = target.parent_requirement or target.atomic_requirement
        if value and value not in seen:
            seen.append(value)
    return seen




def _to_gap_items(value: Any) -> list[dict[str, str]]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    out: list[dict[str, str]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        gap = str(raw.get("gap") or raw.get("missing_element") or raw.get("residual_gap") or "").strip()
        if not gap:
            continue
        out.append({
            "dimension": str(raw.get("dimension") or raw.get("missing_dimension") or "explicitness"),
            "gap": gap,
            "severity": str(raw.get("severity") or "moderate"),
            "target_coverage": str(raw.get("target_coverage") or raw.get("coverage_note") or ""),
        })
    return out

def decision_from_llm_result(
    direction: str,
    source: AtomicRequirement,
    result: dict[str, Any],
    candidates_payload: list[dict[str, Any]],
    target_by_id: dict[str, AtomicRequirement],
) -> MappingDecision:
    selected = result.get("selected_candidate_ids") or []
    if isinstance(selected, str):
        selected = [x.strip() for x in selected.split(",") if x.strip()]
    valid_ids = {c["candidate_id"] for c in candidates_payload}
    selected = [sid for sid in selected if sid in valid_ids]

    base_kwargs = {
        "direction": direction,
        "source_id": source.atomic_id,
        "source_requirement": source.atomic_requirement,
        "source_category": source.category,
        "relation_type": str(result.get("relation_type") or "gap"),
        "equivalence_level": str(result.get("equivalence_level") or "Gap"),
        "coverage_level": int(result.get("coverage_level") or 0),
        "match_type": str(result.get("match_type") or "None"),
        "confidence": float(result.get("confidence") or 0.0),
        "justification": str(result.get("justification") or ""),
        "gap": str(result.get("gap") or ""),
        "gap_type": normalize_gap_type(str(result.get("gap_type") or result.get("gap_classification") or ""), int(result.get("coverage_level") or 0), str(result.get("relation_type") or "")),
        "combine_controls": str(result.get("combine_controls") or ""),
        "recommendation": str(result.get("recommendation") or ""),
        "candidates": candidates_payload,
        "dimension_scores": result.get("dimension_scores") if isinstance(result.get("dimension_scores"), dict) else {},
        "gap_dimensions": _to_list(result.get("gap_dimensions")),
        "gap_items": _to_gap_items(result.get("gap_items") or result.get("residual_gaps")),
        "mapping_risk": str(result.get("mapping_risk") or ""),
        "scoring_rationale": str(result.get("scoring_rationale") or ""),
        "b_contribution": str(result.get("b_contribution") or ""),
        **_source_parent_kwargs(source),
    }

    if not selected:
        return MappingDecision(
            selected_candidate_ids=[],
            target_ids=[],
            target_requirements=[],
            target_parent_ids=[],
            target_parent_requirements=[],
            **base_kwargs,
        )

    targets = [target_by_id[sid] for sid in selected]
    return MappingDecision(
        selected_candidate_ids=selected,
        target_ids=[t.atomic_id for t in targets],
        target_requirements=[t.atomic_requirement for t in targets],
        target_parent_ids=_target_parent_ids(targets),
        target_parent_requirements=_target_parent_requirements(targets),
        **base_kwargs,
    )


def heuristic_decision(direction: str, source: AtomicRequirement, candidates_payload: list[dict[str, Any]], target_by_id: dict[str, AtomicRequirement], app_cfg: AppConfig) -> MappingDecision:
    best = candidates_payload[0]
    target = target_by_id[best["candidate_id"]]
    ao = float(best.get("action_object_score", 0))
    combined = float(best.get("combined_score", 0))
    if combined >= 0.72 and ao >= app_cfg.object_action_cap_75_threshold:
        eq, cov, rel, match_type, risk = "Partial", 80, "partial", "Direct", "Medium"
        gap = "Mostly covered by deterministic scoring, but not validated as an exact equivalence."
    elif combined >= 0.45:
        eq, cov, rel, match_type, risk = "Partial", 50, "partial", "Direct", "Medium"
        gap = "The candidate covers part of the obligation but misses material elements."
    else:
        return gap_decision(direction, source, "Low deterministic combined score", candidates_payload)
    return MappingDecision(
        direction=direction,
        source_id=source.atomic_id,
        source_requirement=source.atomic_requirement,
        source_category=source.category,
        selected_candidate_ids=[target.atomic_id],
        target_ids=[target.atomic_id],
        target_requirements=[target.atomic_requirement],
        relation_type=rel,
        equivalence_level=eq,
        coverage_level=cov,
        gap_type="partial_gap" if cov >= 50 else "indirect_support_gap",
        match_type=match_type,
        confidence=0.45,
        justification="Deterministic fallback decision based on combined semantic, keyword, structured and action/object scores.",
        gap=gap,
        gap_items=[{"dimension": "explicitness", "gap": gap, "severity": "moderate", "target_coverage": "Deterministic heuristic only."}],
        combine_controls="",
        recommendation="Review manually before relying on deterministic fallback output.",
        candidates=candidates_payload,
        target_parent_ids=_target_parent_ids([target]),
        target_parent_requirements=_target_parent_requirements([target]),
        mapping_risk=risk,
        scoring_rationale=f"combined={combined:.2f}; action_object={ao:.2f}",
        **_source_parent_kwargs(source),
    )


def gap_decision(direction: str, source: AtomicRequirement, reason: str, candidates: list[dict[str, Any]] | None = None) -> MappingDecision:
    return MappingDecision(
        direction=direction,
        source_id=source.atomic_id,
        source_requirement=source.atomic_requirement,
        source_category=source.category,
        selected_candidate_ids=[],
        target_ids=[],
        target_requirements=[],
        relation_type="true_gap",
        equivalence_level="Gap",
        coverage_level=0,
        match_type="None",
        confidence=1.0,
        justification=reason,
        gap=reason,
        gap_items=[{"dimension": "explicitness", "gap": reason, "severity": "material", "target_coverage": "No sufficient selected target candidate."}],
        gap_type="true_gap",
        combine_controls="",
        recommendation="No sufficient match passed retrieval and judging. In soft_enisa mode, category does not block global fallback.",
        candidates=candidates or [],
        mapping_risk="High",
        scoring_rationale="No candidate passed the retrieval/scope gates.",
        **_source_parent_kwargs(source),
    )


def sanitize_decision(decision: MappingDecision, app_cfg: AppConfig | None = None) -> MappingDecision:
    try:
        cov = int(decision.coverage_level)
    except Exception:
        cov = 0
    decision.coverage_level = min(SCORE_LEVELS, key=lambda x: abs(x - cov))

    # Normalize the richer relationship taxonomy before any rescue/gate logic.
    decision.gap_type = normalize_gap_type(getattr(decision, "gap_type", ""), decision.coverage_level, decision.relation_type)
    decision.relation_type = normalize_relation_type(decision.relation_type, decision.coverage_level, decision.gap_type)

    has_target = bool(decision.target_ids)

    # If the LLM returns Gap while strong retrieval evidence exists, rescue the
    # best candidate as partial/implementation-detail/indirect rather than losing
    # the mapping evidence. This is deliberately marked High risk for review.
    if not has_target:
        rescued = rescue_gap_decision(decision, app_cfg)
        if rescued is not None:
            decision = rescued
            has_target = True

    if not has_target:
        decision.relation_type = "true_gap"
        decision.gap_type = "true_gap"
        decision.equivalence_level = "Gap"
        decision.coverage_level = 0
        decision.match_type = "None"
        decision.selected_candidate_ids = []
        if not decision.gap:
            decision.gap = "No selected target candidate."
        decision.mapping_risk = decision.mapping_risk or "High"
        return decision

    # Post-LLM object/action gate: use it as a score cap, not as a hard rejection.
    max_selected_ao = _max_selected_score(decision, "action_object_score")
    max_allowed = _object_action_max_coverage(app_cfg, max_selected_ao) if app_cfg else 100
    if decision.coverage_level > max_allowed:
        decision.coverage_level = max_allowed
        decision.equivalence_level = _equivalence_from_coverage(max_allowed, decision.relation_type)
        if max_allowed <= 30:
            decision.relation_type = "indirect_support"
            decision.gap_type = "indirect_support_gap"
            decision.match_type = "Indirect"
        elif max_allowed <= 50:
            decision.relation_type = "partial"
            decision.gap_type = decision.gap_type or "partial_gap"
            decision.match_type = "Direct" if decision.match_type not in {"Composite"} else decision.match_type
        decision.mapping_risk = "High"
        gate_msg = (
            f"Coverage capped by object/action gate at {max_allowed}: selected target has insufficient "
            "main action/object alignment for higher coverage. The candidate is kept for traceability; it is not forced to Gap."
        )
        # Keep technical gate information out of business-facing gap fields.
        decision.scoring_rationale = (decision.scoring_rationale + "\n" if decision.scoring_rationale else "") + gate_msg

    if decision.coverage_level == 0:
        # Last rescue attempt if the LLM selected a candidate but still returned
        # coverage 0. If not rescued, it is a true gap and target IDs are removed.
        rescued = rescue_gap_decision(decision, app_cfg, allow_existing_target=True)
        if rescued is not None and rescued.coverage_level > 0:
            decision = rescued
        else:
            decision.relation_type = "true_gap" if decision.relation_type != "conflict" else "conflict"
            decision.gap_type = "conflict_gap" if decision.relation_type == "conflict" else "true_gap"
            decision.equivalence_level = "Gap"
            decision.match_type = "None"
            decision.target_ids = []
            decision.target_requirements = []
            decision.target_parent_ids = []
            decision.target_parent_requirements = []
            decision.selected_candidate_ids = []
            if not decision.gap:
                decision.gap = "No sufficient coverage identified."
            decision.mapping_risk = decision.mapping_risk or "High"
            return decision

    if decision.equivalence_level == "Exact match" and decision.coverage_level < 100:
        decision.equivalence_level = _equivalence_from_coverage(decision.coverage_level, decision.relation_type)
    if decision.equivalence_level == "Exact match" and max_selected_ao < 0.65:
        decision.equivalence_level = "Partial"
        decision.coverage_level = min(decision.coverage_level, 80)
        decision.gap_type = "partial_gap"
        decision.mapping_risk = "High"
        decision.gap = (decision.gap + "\n" if decision.gap else "") + "Exact match downgraded because action/object alignment is insufficient."

    if decision.coverage_level == 100 and decision.equivalence_level not in {"Exact match"}:
        decision.equivalence_level = "Exact match"
        decision.gap_type = "none"
        decision.relation_type = "direct_full_coverage"

    if len(decision.target_ids) > 1:
        decision.match_type = "Composite"
        if not decision.combine_controls:
            decision.combine_controls = ", ".join(decision.target_ids)
    elif decision.match_type in {"", "None"}:
        decision.match_type = "Direct" if decision.coverage_level >= 50 else "Indirect"

    decision = strong_candidate_upgrade(decision, app_cfg)
    decision = apply_coverage_floor(decision, app_cfg)
    decision = apply_not_covered_downgrade(decision, app_cfg)

    decision.gap_type = normalize_gap_type(decision.gap_type, decision.coverage_level, decision.relation_type)
    decision.relation_type = normalize_relation_type(decision.relation_type, decision.coverage_level, decision.gap_type)

    if decision.coverage_level < 100 and not decision.gap:
        decision.gap = "Target framework does not fully cover the source requirement. Review detailed gap items for missing actor/action/object/scope/evidence dimensions."
    if not decision.recommendation and decision.equivalence_level != "Exact match":
        decision.recommendation = "Review manually, especially relation type, gap classification, action/object alignment, scope and evidence differences."
    decision.mapping_risk = decision.mapping_risk or _risk_from_decision(decision)
    return decision


def rescue_gap_decision(decision: MappingDecision, app_cfg: AppConfig | None, *, allow_existing_target: bool = False) -> MappingDecision | None:
    """Convert over-strict Gap decisions into traceable partial/indirect mappings.

    This does not create high-confidence coverage. It keeps the best candidate
    visible when retrieval evidence is strong enough, tags the mapping as High
    risk, and classifies the residual problem as partial_gap,
    implementation_detail_gap, or indirect_support_gap.
    """
    if not app_cfg or not getattr(app_cfg, "enable_candidate_rescue", True):
        return None
    if not decision.candidates:
        return None
    best = _best_candidate(decision.candidates)
    if not best:
        return None
    combined = _float(best.get("combined_score"))
    semantic = _float(best.get("semantic_score"))
    structured = _float(best.get("structured_score"))
    ao = _float(best.get("action_object_score"))
    category_prior = _float(best.get("category_prior_score"))

    candidate_id = str(best.get("candidate_id") or "")
    requirement = str(best.get("requirement") or "")
    parent_id = str(best.get("parent_id") or candidate_id)
    parent_requirement = str(best.get("parent_requirement") or requirement)
    if not candidate_id:
        return None

    rescue_type = ""
    coverage = 0
    equivalence = "Gap"
    relation = "true_gap"
    match_type = "None"
    reason = ""

    # Strong enough for direct partial coverage. This is intentionally less
    # punitive than v3.5: a good semantic/structured candidate should not vanish
    # as Gap solely because action-object lexical overlap is imperfect.
    if combined >= app_cfg.candidate_rescue_partial_combined_threshold and semantic >= app_cfg.candidate_rescue_partial_semantic_threshold:
        rescue_type = "partial_gap"
        coverage = 50 if ao < app_cfg.object_action_cap_75_threshold else 80
        equivalence = "Partial"
        relation = "partial"
        match_type = "Candidate rescue - partial"
        reason = "The best candidate has material semantic and structured overlap; treat as partial coverage with high review risk rather than true gap."
    elif combined >= app_cfg.candidate_rescue_implementation_combined_threshold and (structured >= 0.25 or semantic >= 0.55 or category_prior >= 0.20):
        rescue_type = "implementation_detail_gap"
        coverage = 50
        equivalence = "Partial"
        relation = "implementation_detail_gap"
        match_type = "Candidate rescue - implementation detail"
        reason = "The target appears to cover the same governance/control area but lacks implementation detail, explicitness or evidence."
    elif combined >= app_cfg.candidate_rescue_indirect_combined_threshold or semantic >= app_cfg.candidate_rescue_indirect_semantic_threshold:
        rescue_type = "indirect_support_gap"
        coverage = 20
        equivalence = "Indirect"
        relation = "indirect_support"
        match_type = "Candidate rescue - indirect"
        reason = "The target is related/supportive but does not provide direct coverage."
    else:
        return None

    decision.selected_candidate_ids = [candidate_id]
    decision.target_ids = [candidate_id]
    decision.target_requirements = [requirement]
    decision.target_parent_ids = [parent_id]
    decision.target_parent_requirements = [parent_requirement]
    decision.coverage_level = coverage
    decision.equivalence_level = equivalence
    decision.relation_type = relation
    decision.gap_type = rescue_type
    decision.match_type = match_type
    decision.confidence = min(float(decision.confidence or 0.45), 0.55)
    decision.mapping_risk = "High"
    rescue_note = f"{reason} Candidate rescue scores: combined={combined:.2f}, semantic={semantic:.2f}, structured={structured:.2f}, action_object={ao:.2f}."
    decision.justification = (decision.justification + "\n" if decision.justification else "") + rescue_note
    decision.gap = (decision.gap + "\n" if decision.gap else "") + rescue_note
    decision.gap_items.append({
        "dimension": "explicitness" if rescue_type == "implementation_detail_gap" else "action",
        "gap": reason,
        "severity": "material" if coverage <= 20 else "moderate",
        "target_coverage": f"Candidate {candidate_id} retained for traceability; manual validation required.",
    })
    decision.scoring_rationale = (decision.scoring_rationale + "\n" if decision.scoring_rationale else "") + rescue_note
    return decision



def strong_candidate_upgrade(decision: MappingDecision, app_cfg: AppConfig | None) -> MappingDecision:
    """Upgrade under-scored strong candidates.

    Tier 1 (75%): combined + semantic + action_object all above recalibrated thresholds,
    no material gap items. Addresses systemic LLM under-scoring.

    Tier 2 (100%): very high semantic + action_object, zero gap items. Produces exact
    matches for clearly identical obligations where the LLM stopped short.
    """
    if not app_cfg or not getattr(app_cfg, "strong_candidate_upgrade_enabled", True):
        return decision
    if not decision.target_ids or not decision.candidates:
        return decision
    if decision.coverage_level >= 100:
        return decision
    best = _best_candidate(decision.candidates)
    if not best:
        return decision
    combined = _float(best.get("combined_score"))
    semantic = _float(best.get("semantic_score"))
    ao = _float(best.get("action_object_score"))
    structured = _float(best.get("structured_score"))
    material_gap = any(
        str(item.get("severity", "")).casefold() in {"material", "major", "critical"}
        for item in (decision.gap_items or [])
        if isinstance(item, dict)
    )

    # Tier 2 — Exact match (100%)
    if (
        decision.coverage_level >= 80
        and combined >= app_cfg.strong_candidate_upgrade_exact_combined_threshold
        and semantic >= app_cfg.strong_candidate_upgrade_exact_semantic_threshold
        and ao >= app_cfg.strong_candidate_upgrade_action_object_threshold
        and not decision.gap_items
        and not material_gap
    ):
        decision.coverage_level = 100
        decision.equivalence_level = "Exact match"
        decision.relation_type = "direct_full_coverage"
        decision.gap_type = "none"
        decision.gap = ""
        decision.mapping_risk = "Low"
        note = (
            f"Strong candidate upgrade (Exact match): retrieval evidence and absence of residual gaps "
            f"support full coverage (combined={combined:.2f}, semantic={semantic:.2f}, action_object={ao:.2f})."
        )
        decision.scoring_rationale = (decision.scoring_rationale + "\n" if decision.scoring_rationale else "") + note
        return decision

    # Tier 1 — Mostly covered (80%)
    if decision.coverage_level >= 80:
        return decision
    if (
        combined >= app_cfg.strong_candidate_upgrade_combined_threshold
        and semantic >= app_cfg.strong_candidate_upgrade_semantic_threshold
        and ao >= app_cfg.strong_candidate_upgrade_action_object_threshold
        and structured >= app_cfg.strong_candidate_upgrade_structured_threshold
        and not material_gap
    ):
        decision.coverage_level = 80
        decision.equivalence_level = "Partial"
        decision.relation_type = "mostly_covered"
        decision.gap_type = "implementation_detail_gap" if decision.gap_items else "partial_gap"
        decision.mapping_risk = decision.mapping_risk or "Medium"
        note = (
            f"Strong candidate upgrade (Mostly covered): high retrieval evidence overrides weaker LLM classification "
            f"(combined={combined:.2f}, semantic={semantic:.2f}, structured={structured:.2f}, action_object={ao:.2f})."
        )
        decision.scoring_rationale = (decision.scoring_rationale + "\n" if decision.scoring_rationale else "") + note
    return decision

def apply_coverage_floor(decision: MappingDecision, app_cfg: AppConfig | None) -> MappingDecision:
    """Prevent the LLM from under-scoring strong candidates after gate and upgrade logic.

    Floor 1 (50%): LLM assigned 25% (indirect/gap) but combined score is strong and the
    action/object gate has not capped coverage to 25.

    Floor 2 (75%): Coverage is still ≤50% but semantic + action/object are both high and
    no material gap item was identified.

    Neither floor applies to rescued/high-risk decisions or when the gate caps coverage.
    """
    if not app_cfg or not getattr(app_cfg, "score_floor_enabled", True):
        return decision
    if not decision.target_ids:
        return decision
    if str(decision.mapping_risk or "").casefold() == "high":
        return decision

    best = _best_candidate(decision.candidates)
    if not best:
        return decision

    combined = _float(best.get("combined_score"))
    semantic = _float(best.get("semantic_score"))
    ao = _float(best.get("action_object_score"))
    gate_cap = _object_action_max_coverage(app_cfg, ao) if app_cfg else 100

    material_gap = any(
        str(item.get("severity", "")).casefold() in {"material", "major", "critical"}
        for item in (decision.gap_items or [])
        if isinstance(item, dict)
    )

    # Floor 1 — 50%: combined strong but LLM under-classified as indirect/gap
    if (
        decision.coverage_level <= 30
        and gate_cap > 30
        and combined >= app_cfg.score_floor_combined_threshold
    ):
        decision.coverage_level = 50
        decision.equivalence_level = "Partial"
        if decision.gap_type in {"indirect_support_gap", "true_gap"}:
            decision.gap_type = "partial_gap"
        decision.relation_type = "partial"
        note = (
            f"Coverage floor (50%): strong combined score ({combined:.2f}) overrides under-classification "
            f"— the gate has not capped coverage, suggesting genuine partial overlap."
        )
        decision.scoring_rationale = (decision.scoring_rationale + "\n" if decision.scoring_rationale else "") + note

    # Floor 2 — 80%: high semantic + action/object and no material gap
    if (
        decision.coverage_level <= 50
        and gate_cap >= 80
        and semantic >= app_cfg.score_floor_semantic_threshold
        and ao >= app_cfg.score_floor_action_object_threshold
        and not material_gap
    ):
        decision.coverage_level = 80
        decision.equivalence_level = "Partial"
        decision.relation_type = "mostly_covered"
        if decision.gap_type in {"indirect_support_gap", "true_gap"}:
            decision.gap_type = "partial_gap"
        elif not decision.gap_type or decision.gap_type == "partial_gap":
            decision.gap_type = "implementation_detail_gap" if decision.gap_items else "partial_gap"
        note = (
            f"Coverage floor (80%): high semantic ({semantic:.2f}) and action/object ({ao:.2f}) scores "
            f"support Mostly covered — remaining gap is likely implementation detail."
        )
        decision.scoring_rationale = (decision.scoring_rationale + "\n" if decision.scoring_rationale else "") + note

    return decision



def apply_not_covered_downgrade(decision: MappingDecision, app_cfg: AppConfig | None) -> MappingDecision:
    """Mark very weak indirect decisions as 'Not covered'.

    Tiered logic by coverage level:
    - coverage ≤ 20 (very weak indirect): downgrade if EITHER combined OR semantic
      is below the strict thresholds. These decisions need strong retrieval evidence
      to justify even a 10-20% label; absent that, they are not_covered.
    - coverage = 30 (weak indirect): downgrade only if BOTH combined AND semantic
      are below the standard thresholds. More lenient — 30% with decent semantic
      evidence is kept as indirect.
    Coverage_level is NOT set to 0 — kept at original value to avoid
    triggering the rescue loop if sanitize_decision is called a second time.
    """
    if not app_cfg:
        return decision
    if decision.coverage_level > 30:
        return decision
    if not decision.target_ids:
        return decision

    best = _best_candidate(decision.candidates)
    if not best:
        return decision

    combined = _float(best.get("combined_score"))
    semantic = _float(best.get("semantic_score"))

    if decision.coverage_level <= 20:
        # Strict path: OR logic — needs BOTH scores to be decent to keep the label
        threshold_combined = getattr(app_cfg, "not_covered_strict_combined_threshold", 0.45)
        threshold_semantic = getattr(app_cfg, "not_covered_strict_semantic_threshold", 0.65)
        should_downgrade = combined < threshold_combined or semantic < threshold_semantic
        logic = "OR"
    else:
        # Standard path (30%): AND logic — only downgrade when both scores are very low
        threshold_combined = getattr(app_cfg, "not_covered_combined_threshold", 0.35)
        threshold_semantic = getattr(app_cfg, "not_covered_semantic_threshold", 0.55)
        should_downgrade = combined < threshold_combined and semantic < threshold_semantic
        logic = "AND"

    if should_downgrade:
        decision.equivalence_level = "Not covered"
        decision.relation_type = "not_covered"
        note = (
            f"Not covered (cov={decision.coverage_level}%, {logic} logic): combined={combined:.2f}, "
            f"semantic={semantic:.2f} — retrieval evidence insufficient to justify indirect label."
        )
        decision.scoring_rationale = (decision.scoring_rationale + "\n" if decision.scoring_rationale else "") + note
    return decision


def _best_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid = [c for c in candidates if isinstance(c, dict)]
    if not valid:
        return None
    return sorted(valid, key=lambda c: (_float(c.get("combined_score")), _float(c.get("semantic_score"))), reverse=True)[0]


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def normalize_gap_type(value: str, coverage: int, relation_type: str = "") -> str:
    text = str(value or "").casefold().strip().replace(" ", "_").replace("-", "_")
    rel = str(relation_type or "").casefold().strip().replace(" ", "_").replace("-", "_")
    aliases = {
        "gap": "true_gap",
        "no_match": "true_gap",
        "no_coverage": "true_gap",
        "true_gap": "true_gap",
        "partial": "partial_gap",
        "partial_gap": "partial_gap",
        "partially_covered": "partial_gap",
        "implementation": "implementation_detail_gap",
        "implementation_gap": "implementation_detail_gap",
        "implementation_detail": "implementation_detail_gap",
        "implementation_detail_gap": "implementation_detail_gap",
        "detail_gap": "implementation_detail_gap",
        "indirect": "indirect_support_gap",
        "indirect_support": "indirect_support_gap",
        "supportive": "indirect_support_gap",
        "indirect_support_gap": "indirect_support_gap",
        "conflict": "conflict_gap",
        "conflict_gap": "conflict_gap",
        "none": "none",
        "no_gap": "none",
    }
    if text in aliases:
        return aliases[text]
    if rel in aliases:
        return aliases[rel]
    if coverage >= 100:
        return "none"
    if coverage >= 40:
        return "partial_gap"
    if coverage >= 10:
        return "indirect_support_gap"
    return "true_gap"


def normalize_relation_type(value: str, coverage: int, gap_type: str = "") -> str:
    text = str(value or "").casefold().strip().replace(" ", "_").replace("-", "_")
    aliases = {
        "exact": "direct_full_coverage",
        "exact_match": "direct_full_coverage",
        "full": "direct_full_coverage",
        "mostly_equivalent": "mostly_covered",
        "mostly_covered": "mostly_covered",
        "partial": "partial",
        "partially_covered": "partial",
        "composite": "composite_coverage",
        "composite_coverage": "composite_coverage",
        "implementation_detail_gap": "implementation_detail_gap",
        "indirect": "indirect_support",
        "indirect_support": "indirect_support",
        "supportive": "indirect_support",
        "gap": "true_gap",
        "no_match": "true_gap",
        "true_gap": "true_gap",
        "conflict": "conflict",
        "not_covered": "not_covered",
    }
    if text in aliases:
        normalized = aliases[text]
    elif coverage >= 100:
        normalized = "direct_full_coverage"
    elif coverage >= 80:
        normalized = "mostly_covered"
    elif coverage >= 40:
        normalized = "partial"
    elif coverage >= 10:
        normalized = "indirect_support"
    else:
        normalized = "true_gap"
    if gap_type == "implementation_detail_gap" and coverage > 0:
        return "implementation_detail_gap"
    if gap_type == "partial_gap" and coverage >= 40:
        return "partial"
    return normalized


def _max_selected_score(decision: MappingDecision, score_name: str) -> float:
    selected = set(decision.target_ids or decision.selected_candidate_ids)
    scores = []
    for candidate in decision.candidates:
        if candidate.get("candidate_id") in selected:
            try:
                scores.append(float(candidate.get(score_name) or 0.0))
            except Exception:
                pass
    return max(scores) if scores else 0.0


def _object_action_max_coverage(app_cfg: AppConfig, score: float) -> int:
    if not app_cfg or not app_cfg.enforce_object_action_gate:
        return 100
    mode = getattr(app_cfg, "object_action_gate_mode", "score_cap")
    if mode in {"off", "none", "disabled"}:
        return 100
    if mode in {"hard", "legacy"}:
        return 25 if score < app_cfg.object_action_high_coverage_threshold else 100
    # score_cap mode: weak action/object alignment caps over-optimistic coverage
    # but never removes the selected candidate by itself.
    if score < app_cfg.object_action_cap_25_threshold:
        return 30
    if score < app_cfg.object_action_cap_75_threshold:
        return 50
    return 100


def _risk_from_decision(decision: MappingDecision) -> str:
    if decision.coverage_level <= 20 or decision.equivalence_level == "Gap":
        return "High"
    if decision.coverage_level < 80 or decision.match_type == "Composite":
        return "Medium"
    if decision.coverage_level < 100:
        return "Low"
    return "None"


def _equivalence_from_coverage(coverage: int, relation_type: str = "") -> str:
    if coverage >= 100:
        return "Exact match"
    if coverage >= 40:
        return "Partial"
    if coverage >= 10:
        return "Indirect"
    return "Gap"


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    va = np.array(a[:n], dtype=float)
    vb = np.array(b[:n], dtype=float)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


def bm25_rank(source: AtomicRequirement, candidates: list[AtomicRequirement], k1: float = 1.5, b: float = 0.75) -> list[tuple[str, float]]:
    docs = [candidate_tokens(c) for c in candidates]
    query = candidate_tokens(source)
    if not docs or not query:
        return [(c.atomic_id, 0.0) for c in candidates]
    avgdl = sum(len(d) for d in docs) / max(len(docs), 1)
    df = Counter()
    for doc in docs:
        for term in set(doc):
            df[term] += 1
    n_docs = len(docs)
    scores = []
    for c, doc in zip(candidates, docs):
        tf = Counter(doc)
        score = 0.0
        dl = len(doc) or 1
        for term in query:
            if term not in tf:
                continue
            idf = math.log(1 + (n_docs - df[term] + 0.5) / (df[term] + 0.5))
            numerator = tf[term] * (k1 + 1)
            denominator = tf[term] + k1 * (1 - b + b * dl / (avgdl or 1))
            score += idf * numerator / denominator
        scores.append((c.atomic_id, score))
    max_score = max([s for _, s in scores] or [1.0]) or 1.0
    normalized = [(cid, s / max_score) for cid, s in scores]
    normalized.sort(key=lambda x: x[1], reverse=True)
    return normalized


def candidate_tokens(atom: AtomicRequirement) -> list[str]:
    if atom.keyword_text:
        return tokenize(atom.keyword_text)
    values = [atom.atomic_requirement, atom.category]
    if atom.fields:
        values.extend(str(atom.fields.get(k, "")) for k in ["domain", "actor", "action", "object", "evidence", "control_type"])
    values.extend(atom.keywords or [])
    return tokenize(" ".join(values))


def structured_similarity(a: AtomicRequirement, b: AtomicRequirement) -> float:
    weights = {
        "domain": 0.5,
        "actor": 1.0,
        "action": 2.5,
        "object": 3.0,
        "condition": 1.0,
        "deadline": 1.0,
        "evidence": 1.5,
        "obligation_type": 0.8,
        "control_type": 1.8,
    }
    total = 0.0
    weight = 0.0
    for key, wa in weights.items():
        ta = set(tokenize(str((a.fields or {}).get(key, ""))))
        tb = set(tokenize(str((b.fields or {}).get(key, ""))))
        if not ta and not tb:
            continue
        inter = len(ta & tb)
        union = len(ta | tb) or 1
        total += wa * (inter / union)
        weight += wa
    return total / weight if weight else 0.0


def action_object_similarity(a: AtomicRequirement, b: AtomicRequirement) -> float:
    fa, fb = a.fields or {}, b.fields or {}
    src = " ".join(str(fa.get(k, "")) for k in ["action", "object", "control_type"])
    tgt = " ".join(str(fb.get(k, "")) for k in ["action", "object", "control_type"])
    ta, tb = set(tokenize(src)), set(tokenize(tgt))

    # Control family is derived from all available text including the full requirement.
    # This makes the family bonus fire even when structured fields were not extracted.
    source_fam = _control_family(src + " " + a.atomic_requirement)
    target_fam = _control_family(tgt + " " + b.atomic_requirement)
    family_bonus = 0.25 if source_fam and source_fam == target_fam else 0.0
    family_penalty = -0.25 if source_fam and target_fam and source_fam != target_fam else 0.0

    if not ta or not tb:
        # Fields not extracted: the only signal is the control family.
        # Return a neutral-low score (above the cap_25 gate threshold) when families match
        # so the gate does not hard-cap candidates whose fields were simply not populated.
        if source_fam and source_fam == target_fam:
            return 0.20
        if source_fam and target_fam and source_fam != target_fam:
            return 0.0
        return 0.0

    inter = len(ta & tb)
    jaccard = inter / (len(ta | tb) or 1)
    return max(0.0, min(1.0, jaccard + family_bonus + family_penalty))


def control_type_similarity(a: AtomicRequirement, b: AtomicRequirement) -> float:
    ta = set(tokenize(str((a.fields or {}).get("control_type", ""))))
    tb = set(tokenize(str((b.fields or {}).get("control_type", ""))))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / (len(ta | tb) or 1)


def _control_family(text: str) -> str:
    t = text.casefold()
    families = {
        "access_control": ["access", "accès", "identity", "identité", "authentication", "authent", "authorization", "compte", "account", "privileg", "admin"],
        "awareness_training": ["training", "awareness", "sensibilisation", "formation", "skills", "compétence", "qualification"],
        "incident": ["incident", "notification", "report", "notify", "alerte"],
        "logging_monitoring": ["log", "journal", "monitor", "surveillance", "détection", "trace"],
        "cryptography": ["crypto", "encryption", "chiffrement", "key", "clé"],
        "backup_continuity": ["backup", "sauvegarde", "continuity", "continuité", "recovery", "restoration", "reprise"],
        "asset_inventory": ["asset", "inventory", "inventaire", "actif", "cartographie", "information systems"],
    }
    for fam, words in families.items():
        if any(w in t for w in words):
            return fam
    return ""


def reciprocal_rank_fusion(rankings: dict[str, list[str]], k: int, weights: dict[str, float]) -> list[tuple[str, float]]:
    scores: dict[str, float] = defaultdict(float)
    for name, ranking in rankings.items():
        weight = weights.get(name, 1.0)
        for rank, cid in enumerate(ranking, start=1):
            scores[cid] += weight * (1.0 / (k + rank))
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


def _to_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    return []
