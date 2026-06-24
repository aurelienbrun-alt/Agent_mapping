from __future__ import annotations

import json
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import AppConfig
from .models import AtomicRequirement, CandidateScore, MappingDecision
from .utils import stable_hash


CACHE_SCHEMA_VERSION = "mapping_decision_cache_v4_target_validated_relation_taxonomy"


class MappingDecisionCache:
    """Append-only JSONL cache for expensive pairwise LLM mapping decisions.

    The cache key includes the source atom, selected LLM candidate payload,
    prompt, model and key scoring/gate settings. Re-running the mapper after
    changing only output formatting should therefore reuse previous judge calls.
    """

    def __init__(self, path: Path, *, enabled: bool = True) -> None:
        self.path = path
        self.enabled = enabled
        self._lock = threading.Lock()
        self._items: dict[str, dict[str, Any]] = {}
        if self.enabled:
            self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            key = str(payload.get("key") or "")
            decision = payload.get("decision")
            if key and isinstance(decision, dict):
                self._items[key] = decision

    def get(self, key: str) -> MappingDecision | None:
        if not self.enabled:
            return None
        payload = self._items.get(key)
        if not payload:
            return None
        return _decision_from_dict(payload)

    def set(self, key: str, decision: MappingDecision) -> None:
        if not self.enabled:
            return
        payload = asdict(decision)
        with self._lock:
            if key in self._items:
                return
            self._items[key] = payload
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"key": key, "decision": payload}, ensure_ascii=False, default=str) + "\n")


def build_mapping_cache_key(
    *,
    app_cfg: AppConfig,
    direction: str,
    source: AtomicRequirement,
    candidate_scores: list[CandidateScore],
    target_by_id: dict[str, AtomicRequirement],
) -> str:
    candidates: list[dict[str, Any]] = []
    for score in candidate_scores:
        target = target_by_id.get(score.candidate_id)
        if not target:
            continue
        candidates.append({
            "candidate_id": target.atomic_id,
            "parent_id": target.parent_id,
            "parent_requirement": target.parent_requirement,
            "requirement": target.atomic_requirement,
            "fields": target.fields,
            "primary_category": getattr(target, "primary_category", "") or target.category,
            "secondary_categories": getattr(target, "secondary_categories", []) or [],
            "scores": {
                "semantic": round(score.semantic_score, 5),
                "keyword": round(score.keyword_score, 5),
                "structured": round(score.structured_score, 5),
                "action_object": round(score.action_object_score, 5),
                "control_type": round(score.control_type_score, 5),
                "category_prior": round(score.category_score, 5),
                "combined": round(score.combined_score, 5),
            },
        })
    payload = {
        "schema": CACHE_SCHEMA_VERSION,
        "direction": direction,
        "source": {
            "atomic_id": source.atomic_id,
            "parent_id": source.parent_id,
            "parent_requirement": source.parent_requirement,
            "requirement": source.atomic_requirement,
            "fields": source.fields,
            "primary_category": getattr(source, "primary_category", "") or source.category,
            "secondary_categories": getattr(source, "secondary_categories", []) or [],
        },
        "candidates": candidates,
        "judge_model": app_cfg.azure_openai_judge_deployment,
        "prompt_pairwise_hash": stable_hash(app_cfg.prompt_pairwise_match),
        "output_language": app_cfg.output_language,
        "relation_taxonomy_version": "v4",
        "matching_parameters": {
            "match_scope": app_cfg.match_scope,
            "top_k_candidates": app_cfg.top_k_candidates,
            "llm_top_k_candidates": app_cfg.llm_top_k_candidates,
            "min_candidate_combined_score": app_cfg.min_candidate_combined_score,
            "weights": {
                "semantic": app_cfg.weight_semantic,
                "structured": app_cfg.weight_structured,
                "action_object": app_cfg.weight_action_object,
                "category_prior": app_cfg.weight_category_prior,
                "control_type": app_cfg.weight_control_type,
            },
        },
        "gate": {
            "enabled": app_cfg.enforce_object_action_gate,
            "mode": app_cfg.object_action_gate_mode,
            "cap75": app_cfg.object_action_cap_75_threshold,
            "cap25": app_cfg.object_action_cap_25_threshold,
        },
    }
    return stable_hash(payload)


def _decision_from_dict(payload: dict[str, Any]) -> MappingDecision | None:
    try:
        allowed = set(MappingDecision.__dataclass_fields__.keys())
        clean = {k: v for k, v in payload.items() if k in allowed}
        # Defaults for compatibility with older cache lines.
        for key, default in {
            "candidates": [],
            "final_judge_notes": "",
            "source_parent_id": "",
            "source_parent_requirement": "",
            "source_title": "",
            "target_parent_ids": [],
            "target_parent_requirements": [],
            "dimension_scores": {},
            "gap_dimensions": [],
            "gap_items": [],
            "gap_type": "",
            "parent_gap_summary": "",
            "parent_gap_type": "",
            "mapping_risk": "",
            "scoring_rationale": "",
            "b_contribution": "",
        }.items():
            clean.setdefault(key, default)
        return MappingDecision(**clean)
    except Exception:
        return None
