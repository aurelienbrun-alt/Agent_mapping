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
    # English pivot: `requirement`/`title` always hold the ENGLISH text used by the
    # whole pipeline (atomization, fields, embeddings, judges, output). The source
    # text is kept verbatim here for traceability. Empty when the source was
    # already English or translation is disabled.
    original_requirement: str = ""
    original_title: str = ""
    source_language: str = ""
    # Entity criticality (NIS2): essential is always True in the source data;
    # important indicates whether the requirement also applies to important entities.
    essential: bool = True
    important: bool = False


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
    # English pivot traceability, inherited from the parent RequirementRow.
    parent_requirement_original: str = ""
    source_language: str = ""
    # Entity criticality (NIS2), inherited from the parent RequirementRow.
    essential: bool = True
    important: bool = False


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
    # Judge's deliberate functional-domain verdict from the pairwise decomposition.
    # False = genuinely different domain (definitive true gap): candidate rescue must
    # not override it using retrieval similarity. None = not assessed (rescue as before).
    same_functional_domain: bool | None = None
    # Coverage as decided by the pairwise judge, BEFORE the final judge overwrote it.
    # None when the final judge did not touch this decision. A large |final - pre|
    # overturn is a reliability signal (see output_writer._review_priority).
    pre_final_judge_coverage: int | None = None
