from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

from .utils import as_bool, as_float, as_int, decode_env_prompt, project_root


@dataclass(frozen=True)
class FrameworkConfig:
    name: str
    file: Path
    sheet_name: str | None
    id_column: str
    title_column: str
    requirement_column: str
    category_column: str
    subcategory_column: str = ""
    essential_column: str = ""
    important_column: str = ""


@dataclass(frozen=True)
class AppConfig:
    root: Path

    # Azure OpenAI only. Gemini support has intentionally been removed.
    azure_openai_api_key: str
    azure_openai_endpoint: str
    azure_openai_api_version: str
    azure_openai_text_deployment: str
    azure_openai_judge_deployment: str
    # Final judge can use a stronger model than the pairwise match; empty falls back to the judge deployment.
    azure_openai_final_judge_deployment: str
    azure_openai_category_deployment: str
    azure_openai_embedding_deployment: str
    azure_openai_temperature: float
    azure_openai_embedding_dimensions: int
    dry_run_without_llm: bool

    framework_a: FrameworkConfig
    framework_b: FrameworkConfig

    # Entity criticality (NIS2 essential/important entities)
    enable_entity_criticality: bool

    # Category harmonization
    enable_category_harmonization: bool
    enisa_category_file: Path
    enisa_category_sheet: str | None
    category_harmonization_use_llm: bool
    category_harmonization_force: bool
    category_harmonization_cache_file: str
    category_overrides_file: Path
    repair_cache_categories: bool
    repair_only_low_confidence_categories: bool
    category_strong_confidence_threshold: float
    category_medium_confidence_threshold: float
    category_ambiguity_margin: float
    enable_secondary_category_matching: bool
    max_secondary_categories: int
    category_report_enabled: bool
    prompt_category_harmonization: str

    # Matching / retrieval
    match_scope: str
    category_case_sensitive: bool
    category_trim_spaces: bool
    normalize_language_for_keyword_matching: bool
    pivot_language: str
    use_llm_keyword_normalization: bool
    bidirectional_mapping: bool
    run_final_llm_judge: bool
    final_judge_only_ambiguous: bool
    final_judge_confidence_threshold: float
    final_judge_batch_size: int
    enable_parent_gap_llm_synthesis: bool
    parent_gap_synthesis_only_for_non_full_coverage: bool
    parent_gap_synthesis_max_concurrent_calls: int
    parent_gap_synthesis_max_text_chars: int
    enable_parent_gap_synthesis_cache: bool
    parent_gap_synthesis_cache_file: str

    rebuild_cache: bool
    cache_key_mode: str
    strict_input_cache_validation: bool
    validate_output_target_ids: bool
    invalid_target_id_policy: str
    use_llm_atomization: bool
    use_llm_field_extraction: bool
    max_requirements_per_framework: int

    use_semantic_matching: bool
    use_keyword_matching: bool
    use_structured_field_matching: bool
    use_rrf: bool
    top_k_candidates: int
    rrf_k: int
    weight_semantic: float
    weight_keyword: float
    weight_structured: float
    weight_action_object: float
    weight_control_type: float
    weight_category_prior: float
    min_candidate_combined_score: float
    enforce_object_action_gate: bool
    object_action_high_coverage_threshold: float
    object_action_gate_mode: str
    object_action_cap_75_threshold: float
    object_action_cap_25_threshold: float
    enable_global_fallback: bool
    global_fallback_top_k: int
    use_llm_pairwise_evaluation: bool
    llm_self_review: bool
    llm_self_review_rounds: int
    llm_repeat_on_low_confidence: bool
    llm_confidence_threshold: float
    llm_top_k_candidates: int
    max_concurrent_llm_calls: int
    enable_mapping_decision_cache: bool
    mapping_decision_cache_file: str
    enable_obvious_gap_shortcut: bool
    obvious_gap_combined_threshold: float
    obvious_gap_semantic_threshold: float
    obvious_gap_action_object_threshold: float
    enable_candidate_rescue: bool
    candidate_rescue_partial_combined_threshold: float
    candidate_rescue_partial_semantic_threshold: float
    candidate_rescue_implementation_combined_threshold: float
    candidate_rescue_indirect_combined_threshold: float
    candidate_rescue_indirect_semantic_threshold: float
    strong_candidate_upgrade_enabled: bool
    strong_candidate_upgrade_combined_threshold: float
    strong_candidate_upgrade_semantic_threshold: float
    strong_candidate_upgrade_action_object_threshold: float
    strong_candidate_upgrade_structured_threshold: float
    strong_candidate_upgrade_exact_combined_threshold: float
    strong_candidate_upgrade_exact_semantic_threshold: float
    score_floor_enabled: bool
    score_floor_combined_threshold: float
    score_floor_semantic_threshold: float
    score_floor_action_object_threshold: float
    not_covered_combined_threshold: float
    not_covered_semantic_threshold: float
    not_covered_strict_combined_threshold: float
    not_covered_strict_semantic_threshold: float

    # Guideline RAG enrichment
    use_guideline_rag: bool
    guideline_dir: Path
    guideline_top_k: int
    guideline_chunk_size: int
    guideline_chunk_overlap: int

    # Output
    output_template_path: Path
    use_output_template: bool
    output_dir: Path
    log_dir: Path
    report_dir: Path
    docs_cache_dir: Path
    output_filename_pattern: str
    output_main_view: str
    include_atomic_detail_sheets: bool
    output_language: str
    organization_name: str

    # Prompts
    prompt_atomize: str
    prompt_extract_fields: str
    prompt_keyword_normalization: str
    prompt_pairwise_match: str
    prompt_final_judge: str
    prompt_parent_gap_synthesis: str

    # Consolidated framework generation
    run_consolidated_framework: bool
    consolidated_batch_size: int
    consolidated_orphan_threshold: int
    prompt_consolidated_batch: str
    prompt_consolidated_supplement: str

    # Action plan synthesis (final output column)
    enable_action_plan: bool
    action_plan_batch_size: int
    action_plan_max_bullets: int
    enable_action_plan_cache: bool
    action_plan_cache_file: str
    prompt_action_plan: str


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _path(root: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else root / p


def load_config(env_path: str | Path = ".env", overrides: dict[str, str] | None = None) -> AppConfig:
    """Build the application config.

    `overrides` lets a caller (e.g. the web app) inject values without writing to
    the `.env` file — used to pass per-request Azure credentials and the selected
    source/target frameworks. Override values take precedence over `.env` / process
    environment. Empty/None override values are ignored so they fall back to `.env`.
    """
    root = project_root()
    env_file = _path(root, str(env_path))
    load_dotenv(env_file)

    _overrides = {k: v for k, v in (overrides or {}).items() if v not in (None, "")}

    def _env(name: str, default: str = "") -> str:  # shadows module-level _env, adds override support
        if name in _overrides:
            return str(_overrides[name])
        return os.getenv(name, default)

    framework_a = FrameworkConfig(
        name=_env("FRAMEWORK_A_NAME", "FrameworkA"),
        file=_path(root, _env("FRAMEWORK_A_FILE", "data/framework_a.xlsx")),
        sheet_name=_env("A_SHEET_NAME", "").strip() or None,
        id_column=_env("A_ID_COLUMN", "ID"),
        title_column=_env("A_TITLE_COLUMN", "Title"),
        requirement_column=_env("A_REQUIREMENT_COLUMN", "Requirement"),
        category_column=_env("A_CATEGORY_COLUMN", "Category"),
        subcategory_column="",  # intentionally disabled: the enterprise version maps by ENISA category only
        essential_column=_env("A_ESSENTIAL_COLUMN", "Essential"),
        important_column=_env("A_IMPORTANT_COLUMN", "Important"),
    )
    framework_b = FrameworkConfig(
        name=_env("FRAMEWORK_B_NAME", "FrameworkB"),
        file=_path(root, _env("FRAMEWORK_B_FILE", "data/framework_b.xlsx")),
        sheet_name=_env("B_SHEET_NAME", "").strip() or None,
        id_column=_env("B_ID_COLUMN", "ID"),
        title_column=_env("B_TITLE_COLUMN", "Title"),
        requirement_column=_env("B_REQUIREMENT_COLUMN", "Requirement"),
        category_column=_env("B_CATEGORY_COLUMN", "Category"),
        subcategory_column="",
        essential_column=_env("B_ESSENTIAL_COLUMN", "Essential"),
        important_column=_env("B_IMPORTANT_COLUMN", "Important"),
    )

    return AppConfig(
        root=root,
        azure_openai_api_key=_env("AZURE_OPENAI_API_KEY", ""),
        azure_openai_endpoint=_env("AZURE_OPENAI_ENDPOINT", ""),
        azure_openai_api_version=_env("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        azure_openai_text_deployment=_env("AZURE_OPENAI_TEXT_DEPLOYMENT", "gpt-4.1-nano"),
        azure_openai_judge_deployment=_env("AZURE_OPENAI_JUDGE_DEPLOYMENT", _env("AZURE_OPENAI_TEXT_DEPLOYMENT", "gpt-4.1-nano")),
        azure_openai_final_judge_deployment=_env("AZURE_OPENAI_FINAL_JUDGE_DEPLOYMENT", ""),
        azure_openai_category_deployment=_env("AZURE_OPENAI_CATEGORY_DEPLOYMENT", _env("AZURE_OPENAI_TEXT_DEPLOYMENT", "gpt-4.1-nano")),
        azure_openai_embedding_deployment=_env("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"),
        azure_openai_temperature=as_float(_env("AZURE_OPENAI_TEMPERATURE"), 0.1),
        azure_openai_embedding_dimensions=as_int(_env("AZURE_OPENAI_EMBEDDING_DIMENSIONS"), 512),
        dry_run_without_llm=as_bool(_env("DRY_RUN_WITHOUT_LLM", "false"), False),
        framework_a=framework_a,
        framework_b=framework_b,
        enable_entity_criticality=as_bool(_env("ENABLE_ENTITY_CRITICALITY"), False),
        enable_category_harmonization=as_bool(_env("ENABLE_CATEGORY_HARMONIZATION"), True),
        enisa_category_file=_path(root, _env("ENISA_CATEGORY_FILE", "data/enisa_categories.xlsx")),
        enisa_category_sheet=_env("ENISA_CATEGORY_SHEET", "Catégories ENISA").strip() or None,
        category_harmonization_use_llm=as_bool(_env("CATEGORY_HARMONIZATION_USE_LLM"), True),
        category_harmonization_force=as_bool(_env("CATEGORY_HARMONIZATION_FORCE"), False),
        category_harmonization_cache_file=_env("CATEGORY_HARMONIZATION_CACHE_FILE", "category_harmonization.json"),
        category_overrides_file=_path(root, _env("CATEGORY_OVERRIDES_FILE", "config/category_overrides.xlsx")),
        repair_cache_categories=as_bool(_env("REPAIR_CACHE_CATEGORIES"), False),
        repair_only_low_confidence_categories=as_bool(_env("REPAIR_ONLY_LOW_CONFIDENCE_CATEGORIES"), False),
        category_strong_confidence_threshold=as_float(_env("CATEGORY_STRONG_CONFIDENCE_THRESHOLD"), 0.85),
        category_medium_confidence_threshold=as_float(_env("CATEGORY_MEDIUM_CONFIDENCE_THRESHOLD"), 0.60),
        category_ambiguity_margin=as_float(_env("CATEGORY_AMBIGUITY_MARGIN"), 0.15),
        enable_secondary_category_matching=as_bool(_env("ENABLE_SECONDARY_CATEGORY_MATCHING"), True),
        max_secondary_categories=as_int(_env("MAX_SECONDARY_CATEGORIES"), 2),
        category_report_enabled=as_bool(_env("CATEGORY_REPORT_ENABLED"), True),
        prompt_category_harmonization=decode_env_prompt(_env("PROMPT_CATEGORY_HARMONIZATION", "")),
        match_scope=_env("MATCH_SCOPE", "soft_enisa").strip().lower(),
        category_case_sensitive=as_bool(_env("CATEGORY_CASE_SENSITIVE"), False),
        category_trim_spaces=as_bool(_env("CATEGORY_TRIM_SPACES"), True),
        normalize_language_for_keyword_matching=as_bool(_env("NORMALIZE_LANGUAGE_FOR_KEYWORD_MATCHING"), False),
        pivot_language=_env("PIVOT_LANGUAGE", "en"),
        use_llm_keyword_normalization=as_bool(_env("USE_LLM_KEYWORD_NORMALIZATION"), False),
        bidirectional_mapping=as_bool(_env("BIDIRECTIONAL_MAPPING"), True),
        run_final_llm_judge=as_bool(_env("RUN_FINAL_LLM_JUDGE"), True),
        final_judge_only_ambiguous=as_bool(_env("FINAL_JUDGE_ONLY_AMBIGUOUS"), True),
        final_judge_confidence_threshold=as_float(_env("FINAL_JUDGE_CONFIDENCE_THRESHOLD"), 0.80),
        final_judge_batch_size=as_int(_env("FINAL_JUDGE_BATCH_SIZE"), 25),
        enable_parent_gap_llm_synthesis=as_bool(_env("ENABLE_PARENT_GAP_LLM_SYNTHESIS"), False),
        parent_gap_synthesis_only_for_non_full_coverage=as_bool(_env("PARENT_GAP_SYNTHESIS_ONLY_FOR_NON_FULL_COVERAGE"), True),
        parent_gap_synthesis_max_concurrent_calls=as_int(_env("PARENT_GAP_SYNTHESIS_MAX_CONCURRENT_CALLS"), 0),
        parent_gap_synthesis_max_text_chars=as_int(_env("PARENT_GAP_SYNTHESIS_MAX_TEXT_CHARS"), 1000),
        enable_parent_gap_synthesis_cache=as_bool(_env("ENABLE_PARENT_GAP_SYNTHESIS_CACHE"), True),
        parent_gap_synthesis_cache_file=_env("PARENT_GAP_SYNTHESIS_CACHE_FILE", "parent_gap_synthesis_cache.jsonl"),
        rebuild_cache=as_bool(_env("REBUILD_CACHE"), False),
        cache_key_mode=_env("CACHE_KEY_MODE", "file_name").strip().lower(),
        strict_input_cache_validation=as_bool(_env("STRICT_INPUT_CACHE_VALIDATION"), True),
        validate_output_target_ids=as_bool(_env("VALIDATE_OUTPUT_TARGET_IDS"), True),
        invalid_target_id_policy=_env("INVALID_TARGET_ID_POLICY", "raise").strip().lower(),
        use_llm_atomization=as_bool(_env("USE_LLM_ATOMIZATION"), True),
        use_llm_field_extraction=as_bool(_env("USE_LLM_FIELD_EXTRACTION"), True),
        max_requirements_per_framework=as_int(_env("MAX_REQUIREMENTS_PER_FRAMEWORK"), 0),
        use_semantic_matching=as_bool(_env("USE_SEMANTIC_MATCHING"), True),
        use_keyword_matching=as_bool(_env("USE_KEYWORD_MATCHING"), False),
        use_structured_field_matching=as_bool(_env("USE_STRUCTURED_FIELD_MATCHING"), True),
        use_rrf=as_bool(_env("USE_RRF"), True),
        top_k_candidates=as_int(_env("TOP_K_CANDIDATES"), 8),
        rrf_k=as_int(_env("RRF_K"), 60),
        weight_semantic=as_float(_env("WEIGHT_SEMANTIC"), 0.45),
        weight_keyword=as_float(_env("WEIGHT_KEYWORD"), 0.0),
        weight_structured=as_float(_env("WEIGHT_STRUCTURED"), 0.30),
        weight_action_object=as_float(_env("WEIGHT_ACTION_OBJECT"), 0.20),
        weight_control_type=as_float(_env("WEIGHT_CONTROL_TYPE"), 0.05),
        weight_category_prior=as_float(_env("WEIGHT_CATEGORY_PRIOR"), 0.03),
        min_candidate_combined_score=as_float(_env("MIN_CANDIDATE_COMBINED_SCORE"), 0.04),
        enforce_object_action_gate=as_bool(_env("ENFORCE_OBJECT_ACTION_GATE"), True),
        object_action_high_coverage_threshold=as_float(_env("OBJECT_ACTION_HIGH_COVERAGE_THRESHOLD"), 0.75),
        object_action_gate_mode=_env("OBJECT_ACTION_GATE_MODE", "score_cap").strip().lower(),
        object_action_cap_75_threshold=as_float(_env("OBJECT_ACTION_CAP_75_THRESHOLD"), 0.25),
        object_action_cap_25_threshold=as_float(_env("OBJECT_ACTION_CAP_25_THRESHOLD"), 0.10),
        enable_global_fallback=as_bool(_env("ENABLE_GLOBAL_FALLBACK"), True),
        global_fallback_top_k=as_int(_env("GLOBAL_FALLBACK_TOP_K"), 8),
        use_llm_pairwise_evaluation=as_bool(_env("USE_LLM_PAIRWISE_EVALUATION"), True),
        llm_self_review=as_bool(_env("LLM_SELF_REVIEW"), False),
        llm_self_review_rounds=as_int(_env("LLM_SELF_REVIEW_ROUNDS"), 0),
        llm_repeat_on_low_confidence=as_bool(_env("LLM_REPEAT_ON_LOW_CONFIDENCE"), True),
        llm_confidence_threshold=as_float(_env("LLM_CONFIDENCE_THRESHOLD"), 0.65),
        llm_top_k_candidates=as_int(_env("LLM_TOP_K_CANDIDATES"), 10),
        max_concurrent_llm_calls=as_int(_env("MAX_CONCURRENT_LLM_CALLS"), 4),
        enable_mapping_decision_cache=as_bool(_env("ENABLE_MAPPING_DECISION_CACHE"), True),
        mapping_decision_cache_file=_env("MAPPING_DECISION_CACHE_FILE", "mapping_decisions_cache.jsonl"),
        enable_obvious_gap_shortcut=as_bool(_env("ENABLE_OBVIOUS_GAP_SHORTCUT"), True),
        obvious_gap_combined_threshold=as_float(_env("OBVIOUS_GAP_COMBINED_THRESHOLD"), 0.10),
        obvious_gap_semantic_threshold=as_float(_env("OBVIOUS_GAP_SEMANTIC_THRESHOLD"), 0.20),
        obvious_gap_action_object_threshold=as_float(_env("OBVIOUS_GAP_ACTION_OBJECT_THRESHOLD"), 0.15),
        enable_candidate_rescue=as_bool(_env("ENABLE_CANDIDATE_RESCUE"), True),
        candidate_rescue_partial_combined_threshold=as_float(_env("CANDIDATE_RESCUE_PARTIAL_COMBINED_THRESHOLD"), 0.55),
        candidate_rescue_partial_semantic_threshold=as_float(_env("CANDIDATE_RESCUE_PARTIAL_SEMANTIC_THRESHOLD"), 0.60),
        candidate_rescue_implementation_combined_threshold=as_float(_env("CANDIDATE_RESCUE_IMPLEMENTATION_COMBINED_THRESHOLD"), 0.45),
        candidate_rescue_indirect_combined_threshold=as_float(_env("CANDIDATE_RESCUE_INDIRECT_COMBINED_THRESHOLD"), 0.35),
        candidate_rescue_indirect_semantic_threshold=as_float(_env("CANDIDATE_RESCUE_INDIRECT_SEMANTIC_THRESHOLD"), 0.48),
        strong_candidate_upgrade_enabled=as_bool(_env("STRONG_CANDIDATE_UPGRADE_ENABLED"), True),
        strong_candidate_upgrade_combined_threshold=as_float(_env("STRONG_CANDIDATE_UPGRADE_COMBINED_THRESHOLD"), 0.58),
        strong_candidate_upgrade_semantic_threshold=as_float(_env("STRONG_CANDIDATE_UPGRADE_SEMANTIC_THRESHOLD"), 0.76),
        strong_candidate_upgrade_action_object_threshold=as_float(_env("STRONG_CANDIDATE_UPGRADE_ACTION_OBJECT_THRESHOLD"), 0.18),
        strong_candidate_upgrade_structured_threshold=as_float(_env("STRONG_CANDIDATE_UPGRADE_STRUCTURED_THRESHOLD"), 0.10),
        strong_candidate_upgrade_exact_combined_threshold=as_float(_env("STRONG_CANDIDATE_UPGRADE_EXACT_COMBINED_THRESHOLD"), 0.68),
        strong_candidate_upgrade_exact_semantic_threshold=as_float(_env("STRONG_CANDIDATE_UPGRADE_EXACT_SEMANTIC_THRESHOLD"), 0.84),
        score_floor_enabled=as_bool(_env("SCORE_FLOOR_ENABLED"), True),
        score_floor_combined_threshold=as_float(_env("SCORE_FLOOR_COMBINED_THRESHOLD"), 0.60),
        score_floor_semantic_threshold=as_float(_env("SCORE_FLOOR_SEMANTIC_THRESHOLD"), 0.80),
        score_floor_action_object_threshold=as_float(_env("SCORE_FLOOR_ACTION_OBJECT_THRESHOLD"), 0.20),
        not_covered_combined_threshold=as_float(_env("NOT_COVERED_COMBINED_THRESHOLD"), 0.50),
        not_covered_semantic_threshold=as_float(_env("NOT_COVERED_SEMANTIC_THRESHOLD"), 0.70),
        not_covered_strict_combined_threshold=as_float(_env("NOT_COVERED_STRICT_COMBINED_THRESHOLD"), 0.45),
        not_covered_strict_semantic_threshold=as_float(_env("NOT_COVERED_STRICT_SEMANTIC_THRESHOLD"), 0.65),
        use_guideline_rag=as_bool(_env("USE_GUIDELINE_RAG"), False),
        guideline_dir=_path(root, _env("GUIDELINE_DIR", "data/guidelines")),
        guideline_top_k=as_int(_env("GUIDELINE_TOP_K"), 3),
        guideline_chunk_size=as_int(_env("GUIDELINE_CHUNK_SIZE"), 400),
        guideline_chunk_overlap=as_int(_env("GUIDELINE_CHUNK_OVERLAP"), 80),
        output_template_path=_path(root, _env("OUTPUT_TEMPLATE_PATH", "templates/Professional mapping template.xlsx")),
        use_output_template=as_bool(_env("USE_OUTPUT_TEMPLATE"), False),
        output_dir=_path(root, _env("OUTPUT_DIR", "output")),
        log_dir=_path(root, _env("LOG_DIR", "logs")),
        report_dir=_path(root, _env("REPORT_DIR", "reports")),
        docs_cache_dir=_path(root, _env("DOCS_CACHE_DIR", "docs/cache")),
        output_filename_pattern=_env("OUTPUT_FILENAME_PATTERN", "mapping_{framework_a}_{framework_b}_{date}_{time}.xlsx"),
        output_main_view=_env("OUTPUT_MAIN_VIEW", "parent").strip().lower(),
        include_atomic_detail_sheets=as_bool(_env("INCLUDE_ATOMIC_DETAIL_SHEETS"), True),
        output_language=_env("OUTPUT_LANGUAGE", "fr"),
        organization_name=_env("ORGANIZATION_NAME", ""),
        prompt_atomize=decode_env_prompt(_env("PROMPT_ATOMIZE", "")),
        prompt_extract_fields=decode_env_prompt(_env("PROMPT_EXTRACT_FIELDS", "")),
        prompt_keyword_normalization=decode_env_prompt(_env("PROMPT_KEYWORD_NORMALIZATION", "")),
        prompt_pairwise_match=decode_env_prompt(_env("PROMPT_PAIRWISE_MATCH", "")),
        prompt_final_judge=decode_env_prompt(_env("PROMPT_FINAL_JUDGE", "")),
        prompt_parent_gap_synthesis=decode_env_prompt(_env("PROMPT_PARENT_GAP_SYNTHESIS", "")),
        run_consolidated_framework=as_bool(_env("RUN_CONSOLIDATED_FRAMEWORK"), False),
        consolidated_batch_size=as_int(_env("CONSOLIDATED_BATCH_SIZE"), 20),
        consolidated_orphan_threshold=as_int(_env("CONSOLIDATED_ORPHAN_THRESHOLD"), 40),
        prompt_consolidated_batch=decode_env_prompt(_env("PROMPT_CONSOLIDATED_BATCH", "")),
        prompt_consolidated_supplement=decode_env_prompt(_env("PROMPT_CONSOLIDATED_SUPPLEMENT", "")),
        enable_action_plan=as_bool(_env("ENABLE_ACTION_PLAN"), False),
        action_plan_batch_size=as_int(_env("ACTION_PLAN_BATCH_SIZE"), 20),
        action_plan_max_bullets=as_int(_env("ACTION_PLAN_MAX_BULLETS"), 4),
        enable_action_plan_cache=as_bool(_env("ENABLE_ACTION_PLAN_CACHE"), True),
        action_plan_cache_file=_env("ACTION_PLAN_CACHE_FILE", "action_plan_cache.jsonl"),
        prompt_action_plan=decode_env_prompt(_env("PROMPT_ACTION_PLAN", "")),
    )


def validate_config(cfg: AppConfig) -> list[str]:
    """Valide la coherence de la configuration.

    Leve ValueError pour les incoherences bloquantes (a appeler tot, avant tout
    traitement). Retourne une liste de warnings non bloquants (a logger/afficher).
    """
    warnings: list[str] = []

    supported_scopes = {"same_enisa_category", "same_category", "soft_enisa", "soft_enisa_category", "all"}
    if cfg.match_scope not in supported_scopes:
        raise ValueError(
            f"MATCH_SCOPE invalide: {cfg.match_scope!r}. Valeurs acceptees: {sorted(supported_scopes)}"
        )

    if cfg.invalid_target_id_policy not in {"raise", "drop", "sanitize", "convert_to_gap"}:
        raise ValueError(
            f"INVALID_TARGET_ID_POLICY invalide: {cfg.invalid_target_id_policy!r}. "
            "Valeurs acceptees: raise, drop, sanitize, convert_to_gap."
        )

    weight_sum = (
        cfg.weight_semantic + cfg.weight_keyword + cfg.weight_structured
        + cfg.weight_action_object + cfg.weight_control_type
    )
    if weight_sum <= 0:
        raise ValueError("Tous les poids de matching sont a 0 — aucun score ne peut etre calcule.")

    if not cfg.dry_run_without_llm and not cfg.azure_openai_api_key:
        raise ValueError("AZURE_OPENAI_API_KEY manquante (ou activer DRY_RUN_WITHOUT_LLM=true).")

    # --- Warnings non bloquants ---
    if cfg.use_semantic_matching and cfg.weight_semantic <= 0:
        warnings.append("USE_SEMANTIC_MATCHING=true mais WEIGHT_SEMANTIC=0 : l'embedding ne pese rien dans le score.")

    if cfg.run_consolidated_framework and not cfg.bidirectional_mapping:
        warnings.append(
            "RUN_CONSOLIDATED_FRAMEWORK=true mais BIDIRECTIONAL_MAPPING=false : "
            "le Pass 2 (exigences propres a B) sera ignore. Le framework consolide "
            "ne contiendra que A enrichi par B."
        )

    if cfg.run_consolidated_framework and not (cfg.prompt_consolidated_batch or "").strip():
        warnings.append(
            "RUN_CONSOLIDATED_FRAMEWORK=true mais PROMPT_CONSOLIDATED_BATCH est vide : "
            "le texte consolide sera une simple copie de A (aucun appel LLM de consolidation)."
        )

    return warnings
