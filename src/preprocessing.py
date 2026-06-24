from __future__ import annotations

from dataclasses import asdict
from typing import Any

from tqdm import tqdm

from .config import AppConfig, FrameworkConfig
from .excel_io import read_framework_excel
from .azure_openai_client import AzureOpenAIClient
from .models import AtomicRequirement, RequirementRow
from .category_harmonizer import harmonize_rows_to_enisa_categories
from .category_taxonomy import repair_atoms_categories
from .utils import normalize_text, tokenize, render_prompt
from .cache import (
    cache_dir,
    cache_mode_description,
    load_processed_cache,
    load_atomized_cache,
    load_fields_cache,
    save_processed_cache,
    save_atomized_cache,
    save_fields_cache,
)
from .logging_utils import JsonlRunLogger


def active_embedding_model_name(app_cfg: AppConfig) -> str:
    dep = getattr(app_cfg, "azure_openai_embedding_deployment", "")
    dims = getattr(app_cfg, "azure_openai_embedding_dimensions", 0)
    return f"{dep} ({dims} dims)" if dims else dep


def process_framework(framework_cfg: FrameworkConfig, app_cfg: AppConfig, llm: AzureOpenAIClient, logger: JsonlRunLogger) -> list[AtomicRequirement]:
    cdir = cache_dir(framework_cfg, app_cfg)
    logger.event(
        "cache.lookup",
        framework=framework_cfg.name,
        cache_mode=cache_mode_description(app_cfg),
        cache_dir=str(cdir),
        rebuild_cache=app_cfg.rebuild_cache,
    )
    cached = load_processed_cache(framework_cfg, app_cfg)
    if cached is not None:
        logger.event("cache.load", framework=framework_cfg.name, count=len(cached), cache_dir=str(cdir))
        if app_cfg.repair_cache_categories:
            cached = repair_atoms_categories(cached, framework_cfg, app_cfg, llm, logger, save_cache=True)
        return cached

    logger.event("framework.read.start", framework=framework_cfg.name, file=str(framework_cfg.file))
    rows = read_framework_excel(framework_cfg, app_cfg)
    logger.event("framework.read.done", framework=framework_cfg.name, requirements=len(rows))

    # Enterprise category harmonization: only executed when the processed framework cache is absent
    # or REBUILD_CACHE=true. No subcategory is used in this edition.
    rows = harmonize_rows_to_enisa_categories(rows, framework_cfg, app_cfg, llm, logger)

    atoms = load_atomized_cache(framework_cfg, app_cfg)
    if atoms is not None:
        logger.event("cache.load.atomized", framework=framework_cfg.name, count=len(atoms), cache_dir=str(cdir))
    else:
        atoms = []
        for row in tqdm(rows, desc=f"Atomize/extract {framework_cfg.name}"):
            row_atoms = atomize_row(row, app_cfg, llm)
            atoms.extend(row_atoms)
        save_atomized_cache(framework_cfg, app_cfg, atoms)
        logger.event("cache.save.atomized", framework=framework_cfg.name, count=len(atoms), cache_dir=str(cdir))

    logger.event("framework.atomization.done", framework=framework_cfg.name, atomic_requirements=len(atoms))

    fields_cached = load_fields_cache(framework_cfg, app_cfg)
    if fields_cached is not None and len(fields_cached) == len(atoms):
        atoms = fields_cached
        logger.event("cache.load.fields", framework=framework_cfg.name, count=len(atoms), cache_dir=str(cdir))

    checkpoint_every = 10
    for idx, atom in enumerate(tqdm(atoms, desc=f"Fields {framework_cfg.name}"), start=1):
        if _has_fields(atom):
            continue
        atom.fields = extract_fields(atom, app_cfg, llm)
        kws = atom.fields.get("keywords") if isinstance(atom.fields, dict) else None
        atom.keywords = _clean_keywords(kws) or tokenize(atom.atomic_requirement)
        if idx % checkpoint_every == 0:
            save_fields_cache(framework_cfg, app_cfg, atoms)
            logger.event("cache.checkpoint.fields", framework=framework_cfg.name, processed=idx, total=len(atoms))
    # Refine categories at atomic level after fields are extracted. This preserves
    # atomization and fields and makes category errors non-blocking downstream.
    atoms = repair_atoms_categories(atoms, framework_cfg, app_cfg, llm, logger, save_cache=False)

    # Keyword/BM25 matching is disabled by default in v3.6 because it adds cost
    # through keyword normalization and has proven less reliable than embeddings +
    # structured fields. Keep this optional for backward compatibility.
    if app_cfg.use_keyword_matching or app_cfg.use_llm_keyword_normalization:
        for atom in tqdm(atoms, desc=f"Keyword pivot {framework_cfg.name}"):
            if not getattr(atom, "keyword_text", ""):
                normalize_keyword_language(atom, app_cfg, llm)
    else:
        for atom in atoms:
            if not getattr(atom, "keyword_text", ""):
                atom.keyword_text = ""
    save_fields_cache(framework_cfg, app_cfg, atoms)

    logger.event(
        "framework.extraction.done",
        framework=framework_cfg.name,
        atomic_requirements=len(atoms),
        keyword_matching=app_cfg.use_keyword_matching,
        keyword_language_normalization=app_cfg.normalize_language_for_keyword_matching and app_cfg.use_llm_keyword_normalization,
        pivot_language=app_cfg.pivot_language,
    )

    embedded_count = sum(1 for a in atoms if getattr(a, "embedding", None))
    missing = [a for a in atoms if not getattr(a, "embedding", None)]
    batch_size = 64
    for start in tqdm(range(0, len(missing), batch_size), desc=f"Embeddings {framework_cfg.name}"):
        batch = missing[start:start + batch_size]
        if not batch:
            continue
        embeddings = llm.embed_texts([embedding_text(atom) for atom in batch])
        for atom, emb in zip(batch, embeddings):
            atom.embedding = emb
        save_fields_cache(framework_cfg, app_cfg, atoms)
        logger.event("cache.checkpoint.embeddings", framework=framework_cfg.name, processed=min(start + batch_size, len(missing)), total=len(missing))
    save_fields_cache(framework_cfg, app_cfg, atoms)
    logger.event(
        "framework.embeddings.done",
        framework=framework_cfg.name,
        embeddings=sum(1 for a in atoms if getattr(a, "embedding", None)),
        already_cached=embedded_count,
        model=active_embedding_model_name(app_cfg),
    )

    save_processed_cache(
        framework_cfg,
        app_cfg,
        atoms,
        metadata={
            "framework": framework_cfg.name,
            "source_file": str(framework_cfg.file),
            "original_requirements": len(rows),
            "atomic_requirements": len(atoms),
            "embedding_model": active_embedding_model_name(app_cfg),
        },
    )
    logger.event("cache.save", framework=framework_cfg.name, count=len(atoms), cache_dir=str(cdir))
    return atoms


def atomize_row(row: RequirementRow, app_cfg: AppConfig, llm: AzureOpenAIClient) -> list[AtomicRequirement]:
    if app_cfg.dry_run_without_llm or not app_cfg.use_llm_atomization:
        parts = heuristic_atomize(row.requirement)
        return [_to_atom(row, i + 1, part, "heuristic") for i, part in enumerate(parts)]

    prompt = render_prompt(app_cfg.prompt_atomize, framework_name=row.framework, source_id=row.source_id, control_id=row.source_id, title=row.title, category=row.category, subcategory=row.subcategory, requirement=row.requirement)
    try:
        result = llm.generate_json(prompt)
        raw_atoms = result.get("atomic_requirements") or []
        if not raw_atoms:
            raw_atoms = [{"text": row.requirement, "rationale": "No atomization returned"}]
        atoms = []
        for i, item in enumerate(raw_atoms):
            text = normalize_text(item.get("text") if isinstance(item, dict) else item)
            if text:
                rationale = normalize_text(item.get("rationale", "") if isinstance(item, dict) else "")
                atoms.append(_to_atom(row, i + 1, text, rationale))
        return atoms or [_to_atom(row, 1, row.requirement, "fallback_empty_atomization")]
    except Exception as exc:
        parts = heuristic_atomize(row.requirement)
        return [_to_atom(row, i + 1, part, f"fallback_after_error: {exc}") for i, part in enumerate(parts)]


def extract_fields(atom: AtomicRequirement, app_cfg: AppConfig, llm: AzureOpenAIClient) -> dict[str, Any]:
    if app_cfg.dry_run_without_llm or not app_cfg.use_llm_field_extraction:
        return heuristic_fields(atom.atomic_requirement, atom.category)
    prompt = render_prompt(app_cfg.prompt_extract_fields, category=atom.category, subcategory=atom.subcategory, atomic_requirement=atom.atomic_requirement)
    try:
        result = llm.generate_json(prompt)
        if not isinstance(result, dict):
            return heuristic_fields(atom.atomic_requirement, atom.category)
        return result
    except Exception:
        return heuristic_fields(atom.atomic_requirement, atom.category)


def normalize_keyword_language(atom: AtomicRequirement, app_cfg: AppConfig, llm: AzureOpenAIClient) -> None:
    """Create a pivot-language text used by keyword/BM25 matching only.

    The original atomic requirement is preserved for the final Excel output and for LLM judging.
    """
    default_text = keyword_matching_text(atom)
    if not app_cfg.normalize_language_for_keyword_matching:
        atom.keyword_text = default_text
        return
    if app_cfg.dry_run_without_llm or not app_cfg.use_llm_keyword_normalization:
        # In dry-run mode we cannot translate. We still populate the field so the rest of
        # the pipeline uses one stable code path.
        atom.keyword_text = default_text
        return
    prompt = render_prompt(
        app_cfg.prompt_keyword_normalization,
        pivot_language=app_cfg.pivot_language,
        atomic_requirement=atom.atomic_requirement,
        category=atom.category,
        subcategory=atom.subcategory,
        fields=atom.fields,
        keywords=atom.keywords,
    )
    try:
        result = llm.generate_json(prompt)
        normalized_text = normalize_text(result.get("keyword_text", "")) if isinstance(result, dict) else ""
        normalized_keywords = _clean_keywords(result.get("keywords")) if isinstance(result, dict) else []
        if normalized_text:
            atom.keyword_text = normalized_text
        else:
            atom.keyword_text = default_text
        if normalized_keywords:
            # Keep keywords in the pivot language too, because candidate_tokens uses them.
            atom.keywords = normalized_keywords
    except Exception:
        atom.keyword_text = default_text


def heuristic_atomize(text: str) -> list[str]:
    text = normalize_text(text)
    # Conservative split. It avoids over-splitting short requirements.
    separators = [";", " and shall ", " and must ", " et doit ", " et doivent "]
    parts = [text]
    for sep in separators:
        new_parts: list[str] = []
        for part in parts:
            if sep in part.lower() and len(part) > 120:
                # case-insensitive split while preserving content approximately.
                import re
                new_parts.extend([p.strip(" .") for p in re.split(re.escape(sep), part, flags=re.IGNORECASE) if p.strip(" .")])
            else:
                new_parts.append(part)
        parts = new_parts
    return parts or [text]


def heuristic_fields(text: str, category: str) -> dict[str, Any]:
    toks = tokenize(text)
    return {
        "domain": category,
        "actor": "",
        "action": toks[0] if toks else "",
        "object": " ".join(toks[1:5]),
        "condition": "",
        "deadline": "",
        "evidence": "",
        "obligation_type": "shall/must" if any(t in text.lower() for t in ["shall", "must", "doit", "doivent"]) else "",
        "control_type": "",
        "keywords": toks[:12],
    }


def _to_atom(row: RequirementRow, atom_index: int, text: str, rationale: str) -> AtomicRequirement:
    suffix = f"#{atom_index}" if atom_index > 1 else "#1"
    return AtomicRequirement(
        framework=row.framework,
        atomic_id=f"{row.source_id}{suffix}",
        parent_id=row.source_id,
        title=row.title,
        parent_requirement=row.requirement,
        atomic_requirement=normalize_text(text),
        category=row.category,
        category_key=row.category_key,
        subcategory=row.subcategory,
        row_number=row.row_number,
        atomization_rationale=rationale,
        original_category=row.original_category or row.category,
        category_harmonization_reason=row.category_harmonization_reason,
        category_harmonization_confidence=row.category_harmonization_confidence,
    )


def _has_fields(atom: AtomicRequirement) -> bool:
    # Field extraction should not be re-run just because keyword/BM25 is disabled
    # and keyword_text is intentionally empty. v3.6 previously tied these two
    # concepts together, which caused costly unnecessary field extraction reruns.
    fields = getattr(atom, "fields", None)
    return isinstance(fields, dict) and bool(fields)


def _clean_keywords(value: Any) -> list[str]:
    if isinstance(value, list):
        return [normalize_text(v).lower() for v in value if normalize_text(v)]
    if isinstance(value, str):
        return tokenize(value)
    return []


def keyword_matching_text(atom: AtomicRequirement) -> str:
    fields = atom.fields or {}
    structured = " ".join(str(fields.get(k, "")) for k in ["domain", "actor", "action", "object", "condition", "deadline", "evidence", "control_type"])
    return f"{atom.category} {atom.subcategory} {atom.atomic_requirement} {structured} {' '.join(atom.keywords)}"


def embedding_text(atom: AtomicRequirement) -> str:
    # Embeddings keep the original text plus extracted fields. Keyword language normalization
    # is intentionally not required for semantic embeddings.
    return keyword_matching_text(atom)
