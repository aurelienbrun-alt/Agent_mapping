from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from typing import Any

from tqdm import tqdm

from .config import AppConfig, FrameworkConfig
from .excel_io import read_framework_excel
from .azure_openai_client import AzureOpenAIClient
from .models import AtomicRequirement, RequirementRow
from .category_harmonizer import harmonize_rows_to_enisa_categories
from .category_taxonomy import repair_atoms_categories
from .utils import normalize_text, tokenize, render_prompt, stable_hash, read_json, write_json
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

TRANSLATION_CACHE_FILE = "translations_en.json"


def active_embedding_model_name(app_cfg: AppConfig) -> str:
    dep = getattr(app_cfg, "azure_openai_embedding_deployment", "")
    dims = getattr(app_cfg, "azure_openai_embedding_dimensions", 0)
    return f"{dep} ({dims} dims)" if dims else dep


def _valid_embedding(emb: Any) -> bool:
    """True only for a non-empty numeric vector. Catches None and [] alike."""
    return isinstance(emb, (list, tuple)) and len(emb) > 0


def repair_missing_embeddings(
    atoms: list[AtomicRequirement],
    framework_cfg: FrameworkConfig,
    app_cfg: AppConfig,
    llm: AzureOpenAIClient,
    logger: JsonlRunLogger,
) -> list[AtomicRequirement]:
    """Re-embed atoms whose cached embedding is empty or malformed.

    Because a processed cache is returned verbatim, an atom persisted with
    ``embedding == []`` would otherwise remain permanently unretrievable. This
    guard detects those atoms on load and recomputes only the missing vectors,
    then rewrites the fields and processed caches so the repair persists.
    """
    missing = [a for a in atoms if not _valid_embedding(getattr(a, "embedding", None))]
    if not missing:
        return atoms
    logger.event("cache.repair.embeddings.detected", framework=framework_cfg.name, missing=len(missing), total=len(atoms))
    if app_cfg.dry_run_without_llm:
        logger.event("cache.repair.embeddings.skipped_dry_run", framework=framework_cfg.name, missing=len(missing))
        return atoms
    batch_size = 64
    for start in range(0, len(missing), batch_size):
        batch = missing[start:start + batch_size]
        embeddings = llm.embed_texts([embedding_text(a) for a in batch])
        for atom, emb in zip(batch, embeddings):
            atom.embedding = emb
    save_fields_cache(framework_cfg, app_cfg, atoms)
    save_processed_cache(
        framework_cfg,
        app_cfg,
        atoms,
        metadata={"embedding_model": active_embedding_model_name(app_cfg), "embedding_repair": len(missing)},
    )
    logger.event("cache.repair.embeddings.done", framework=framework_cfg.name, repaired=len(missing), model=active_embedding_model_name(app_cfg))
    return atoms


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
        # A processed cache is returned verbatim, so the embedding step below never
        # runs on a cache hit. Guard against atoms persisted with an empty/malformed
        # embedding (they would stay permanently unretrievable and silently degrade
        # retrieval, e.g. falling back to an off-topic candidate).
        cached = repair_missing_embeddings(cached, framework_cfg, app_cfg, llm, logger)
        return cached

    logger.event("framework.read.start", framework=framework_cfg.name, file=str(framework_cfg.file))
    rows = read_framework_excel(framework_cfg, app_cfg)
    logger.event("framework.read.done", framework=framework_cfg.name, requirements=len(rows))

    # English pivot FIRST: everything downstream (categories, atomization, fields,
    # embeddings, judges, output) must see a single language. Cached per framework.
    rows = translate_rows_to_english(rows, framework_cfg, app_cfg, llm, logger)

    # Enterprise category harmonization: only executed when the processed framework cache is absent
    # or REBUILD_CACHE=true. No subcategory is used in this edition.
    rows = harmonize_rows_to_enisa_categories(rows, framework_cfg, app_cfg, llm, logger)

    atoms = load_atomized_cache(framework_cfg, app_cfg)
    if atoms is not None:
        logger.event("cache.load.atomized", framework=framework_cfg.name, count=len(atoms), cache_dir=str(cdir))
    else:
        atoms = []
        max_workers = max(1, int(getattr(app_cfg, "max_concurrent_llm_calls", 1) or 1))
        if max_workers <= 1 or len(rows) <= 1:
            for row in tqdm(rows, desc=f"Atomize {framework_cfg.name}"):
                atoms.extend(atomize_row(row, app_cfg, llm))
        else:
            # Atomization is independent per row; parallelize the LLM calls but
            # reassemble in the original row order for stable atomic IDs.
            results = [None] * len(rows)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(atomize_row, row, app_cfg, llm): i for i, row in enumerate(rows)}
                for future in tqdm(as_completed(futures), total=len(futures), desc=f"Atomize {framework_cfg.name}"):
                    results[futures[future]] = future.result()
            for row_atoms in results:
                atoms.extend(row_atoms or [])
        save_atomized_cache(framework_cfg, app_cfg, atoms)
        logger.event("cache.save.atomized", framework=framework_cfg.name, count=len(atoms), cache_dir=str(cdir))

    logger.event("framework.atomization.done", framework=framework_cfg.name, atomic_requirements=len(atoms))

    fields_cached = load_fields_cache(framework_cfg, app_cfg)
    if fields_cached is not None and len(fields_cached) == len(atoms):
        atoms = fields_cached
        logger.event("cache.load.fields", framework=framework_cfg.name, count=len(atoms), cache_dir=str(cdir))

    checkpoint_every = 10
    todo = [atom for atom in atoms if not _has_fields(atom)]
    if todo:
        max_workers = max(1, int(getattr(app_cfg, "max_concurrent_llm_calls", 1) or 1))

        def _assign(atom: AtomicRequirement, fields: dict, done: int) -> None:
            # Runs on the main thread only: mutating atoms and writing the cache
            # file must not race with concurrent workers.
            atom.fields = fields
            kws = fields.get("keywords") if isinstance(fields, dict) else None
            atom.keywords = _clean_keywords(kws) or tokenize(atom.atomic_requirement)
            if done % checkpoint_every == 0:
                save_fields_cache(framework_cfg, app_cfg, atoms)
                logger.event("cache.checkpoint.fields", framework=framework_cfg.name, processed=done, total=len(todo))

        if max_workers <= 1:
            for done, atom in enumerate(tqdm(todo, desc=f"Fields {framework_cfg.name}"), start=1):
                _assign(atom, extract_fields(atom, app_cfg, llm), done)
        else:
            # extract_fields is a pure LLM call returning a dict; parallelize it and
            # assign the results back on the main thread.
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(extract_fields, atom, app_cfg, llm): atom for atom in todo}
                for done, future in enumerate(tqdm(as_completed(futures), total=len(futures), desc=f"Fields {framework_cfg.name}"), start=1):
                    _assign(futures[future], future.result(), done)
        save_fields_cache(framework_cfg, app_cfg, atoms)
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


def _translation_cache_key(row: RequirementRow, app_cfg: AppConfig) -> str:
    return stable_hash({
        "title": row.title,
        "requirement": row.requirement,
        "prompt": stable_hash(app_cfg.prompt_translate_requirement),
        "model": getattr(app_cfg, "azure_openai_text_deployment", ""),
    })


def _translate_row(row: RequirementRow, app_cfg: AppConfig, llm: AzureOpenAIClient) -> dict[str, str]:
    """Translate one row to English. Returns {} when the source is already English."""
    prompt = render_prompt(
        app_cfg.prompt_translate_requirement,
        framework_name=row.framework,
        source_id=row.source_id,
        title=row.title,
        requirement=row.requirement,
    )
    result = llm.generate_json(prompt)
    language = normalize_text(str(result.get("source_language") or "")).lower()
    requirement_en = normalize_text(str(result.get("requirement_en") or ""))
    title_en = normalize_text(str(result.get("title_en") or ""))
    # An empty translation must never silently blank a requirement: keep the source.
    if not requirement_en:
        return {"source_language": language or "unknown", "requirement_en": "", "title_en": ""}
    return {"source_language": language or "unknown", "requirement_en": requirement_en, "title_en": title_en}


def translate_rows_to_english(
    rows: list[RequirementRow],
    framework_cfg: FrameworkConfig,
    app_cfg: AppConfig,
    llm: AzureOpenAIClient,
    logger: JsonlRunLogger,
) -> list[RequirementRow]:
    """Rewrite every requirement into English BEFORE atomization (English pivot).

    Runs at row level (one call per parent requirement, not per atom) so the whole
    downstream pipeline — atomization, structured fields, embeddings, judges and the
    output workbook — works on a single language. Cross-language token comparison in
    structured_similarity/action_object_similarity is otherwise near-zero, and that
    is ~55% of the retrieval weight.

    The source text is preserved on the row for traceability. Results are cached in
    the framework cache dir, so re-runs and atomization rebuilds cost nothing.
    """
    if not rows or not getattr(app_cfg, "translate_requirements_to_english", False):
        return rows
    if app_cfg.dry_run_without_llm or not app_cfg.prompt_translate_requirement.strip():
        logger.event("translation.skip", framework=framework_cfg.name,
                     reason="dry_run" if app_cfg.dry_run_without_llm else "no_prompt")
        return rows

    cdir = cache_dir(framework_cfg, app_cfg)
    cdir.mkdir(parents=True, exist_ok=True)
    cache_path = cdir / TRANSLATION_CACHE_FILE
    # read_json raises when the file is absent, and a corrupted cache must degrade
    # to a re-translation, never break the run.
    cache: dict[str, Any] = {}
    if cache_path.exists():
        try:
            loaded = read_json(cache_path)
            cache = loaded if isinstance(loaded, dict) else {}
        except Exception:
            logger.event("translation.cache_unreadable", framework=framework_cfg.name, path=str(cache_path))

    todo = [row for row in rows if _translation_cache_key(row, app_cfg) not in cache]
    if todo:
        max_workers = max(1, int(getattr(app_cfg, "max_concurrent_llm_calls", 1) or 1))
        errors = 0

        def _work(row: RequirementRow) -> tuple[RequirementRow, dict[str, str] | None]:
            try:
                return row, _translate_row(row, app_cfg, llm)
            except Exception:
                return row, None

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(_work, row) for row in todo]
            for future in tqdm(as_completed(futures), total=len(futures), desc=f"Translate {framework_cfg.name}"):
                row, payload = future.result()
                if payload is None:
                    errors += 1
                    continue  # never cache a failure: the next run retries it
                cache[_translation_cache_key(row, app_cfg)] = payload
        write_json(cache_path, cache)
        if errors:
            # A failed translation leaves that requirement in its source language,
            # which silently degrades matching — surface it instead of hiding it.
            print(f"[WARNING] {errors}/{len(todo)} translation(s) FAILED for {framework_cfg.name}: "
                  "those requirements stay in their source language.", flush=True)
            logger.event("translation.errors", framework=framework_cfg.name, failed=errors, total=len(todo))

    translated = 0
    already_en = 0
    for row in rows:
        payload = cache.get(_translation_cache_key(row, app_cfg))
        if not payload:
            continue
        row.source_language = str(payload.get("source_language") or "")
        requirement_en = str(payload.get("requirement_en") or "")
        if not requirement_en or requirement_en == row.requirement:
            already_en += 1
            continue
        row.original_requirement = row.requirement
        row.original_title = row.title
        row.requirement = requirement_en
        title_en = str(payload.get("title_en") or "")
        if title_en:
            row.title = title_en
        translated += 1

    logger.event("translation.done", framework=framework_cfg.name, rows=len(rows),
                 translated=translated, already_english=already_en,
                 languages=sorted({r.source_language for r in rows if r.source_language}))
    print(f"  [Translation] {framework_cfg.name}: {translated} requirement(s) translated to English, "
          f"{already_en} already English.", flush=True)
    return rows


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
        parent_requirement_original=row.original_requirement,
        source_language=row.source_language,
        original_category=row.original_category or row.category,
        category_harmonization_reason=row.category_harmonization_reason,
        category_harmonization_confidence=row.category_harmonization_confidence,
        essential=row.essential,
        important=row.important,
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
