from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RequirementRow:
    framework: str
    source_id: str
    title: str
    requirement: str
    category: str
    category_key: str
    subcategory: str
    row_number: int
    original_category: str = ""
    category_harmonization_reason: str = ""
    category_harmonization_confidence: float = 0.0


@dataclass
class AtomicRequirement:
    framework: str
    atomic_id: str
    parent_id: str
    title: str
    parent_requirement: str
    atomic_requirement: str
    category: str
    category_key: str
    subcategory: str
    row_number: int
    atomization_rationale: str = ""
    fields: dict[str, Any] = field(default_factory=dict)
    keywords: list[str] = field(default_factory=list)
    embedding: list[float] = field(default_factory=list)
    keyword_text: str = ""
    original_category: str = ""
    category_harmonization_reason: str = ""
    category_harmonization_confidence: float = 0.0
    primary_category: str = ""
    secondary_categories: list[str] = field(default_factory=list)
    category_confidence: float = 0.0
    category_status: str = ""
    category_reason: str = ""
    category_method: str = ""
    category_scores: dict[str, Any] = field(default_factory=dict)


@dataclass
class CandidateScore:
    candidate_id: str
    semantic_score: float = 0.0
    keyword_score: float = 0.0
    structured_score: float = 0.0
    action_object_score: float = 0.0
    control_type_score: float = 0.0
    category_score: float = 0.0
    rrf_score: float = 0.0
    combined_score: float = 0.0
    final_rank: int = 0
    hard_gate: str = "pass"


@dataclass
class MappingDecision:
    direction: str
    source_id: str
    source_requirement: str
    source_category: str
    selected_candidate_ids: list[str]
    target_ids: list[str]
    target_requirements: list[str]
    relation_type: str
    equivalence_level: str
    coverage_level: int
    match_type: str
    confidence: float
    justification: str
    gap: str
    combine_controls: str
    recommendation: str
    candidates: list[dict[str, Any]] = field(default_factory=list)
    final_judge_notes: str = ""
    source_parent_id: str = ""
    source_parent_requirement: str = ""
    source_title: str = ""
    target_parent_ids: list[str] = field(default_factory=list)
    target_parent_requirements: list[str] = field(default_factory=list)
    dimension_scores: dict[str, Any] = field(default_factory=dict)
    gap_dimensions: list[str] = field(default_factory=list)
    gap_items: list[dict[str, Any]] = field(default_factory=list)
    gap_type: str = ""
    parent_gap_summary: str = ""
    parent_gap_type: str = ""
    mapping_risk: str = ""
    scoring_rationale: str = ""
    b_contribution: str = ""
