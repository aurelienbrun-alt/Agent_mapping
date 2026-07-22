"""Recall-injection of category/family-affine candidates.

The embedding top-K sometimes misses a genuinely relevant target because its
cosine rank falls just past the cut (observed on governance requirements whose
France counterparts sit in the PSSI/ROLE families). This module adds those
atoms back — as a UNION with the embedding top-K, never a filter.

Design guarantees (why this cannot lose information):
- Injection only APPENDS candidates already scored by retrieval; it never
  removes an embedding-ranked candidate. Worst case = today's behaviour.
- A wrong source category can therefore only add a few off-topic candidates
  (which the judge discards), never hide the right one.
- Both frameworks are harmonized to the same ENISA taxonomy, so same-category
  injection needs no hand-authored data. The optional family table only ADDS
  cross-category reach and is human-reviewable.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import AppConfig
from .models import AtomicRequirement, CandidateScore
from .utils import normalize_category


# Default cross-category affinity, keyed by the coarse — and near-error-free —
# CyFun/NIST-CSF function code (GV/ID/PR/DE/RS/RC), mapping to France target
# family prefixes. Family names below MUST match the exact target family prefix
# (the token before the first '.' in a control id, e.g. "MCO_MCS.c" -> "MCO_MCS"),
# because injection matches on `family_of(target) in affine_families` — a short
# alias like "MCO" would NOT match the real family "MCO_MCS".
# This is a starter table: edit FAMILY_AFFINITY_FILE to override/extend it.
DEFAULT_AFFINITY: dict[str, list[str]] = {
    "GV": ["PSSI", "ROLE", "RISKS", "COMPLIANCE", "ECOSYSTEM", "CONTRACT", "AUDIT"],
    # ID (Identify) was previously ABSENT — asset-management/inventory (ID.AM),
    # risk-assessment (ID.RA) and improvement (ID.IM) controls therefore received
    # no cross-category reach toward the France inventory/mapping/risk families.
    "ID": ["IS_INVENTORY", "MAPPING", "ECOSYSTEM", "CONTRACT", "RISKS",
           "MCO_MCS", "AUDIT", "COMPLIANCE", "EXERCISES"],
    "PR": ["SEGMENTATION", "FILTERING", "AUTHENTICATION", "ACCESS_RIGHTS",
           "ADMIN_ACCOUNT", "ADMINISTRATION", "CONFIGURATION", "PROT_MALICIOUS_CODE",
           "PHYSICAL_ACCESS", "REMOTE_ACCESS", "DIRECTORIES", "HR", "RH",
           "BUSINESS_CONTINUITY", "IDENTIFICATION", "IS_INVENTORY", "MCO_MCS"],
    "DE": ["MONITORING", "AUDIT", "INCIDENT", "MCO_MCS"],
    "RS": ["INCIDENT", "CRISIS_MANAGEMENT"],
    "RC": ["BUSINESS_CONTINUITY", "CRISIS_MANAGEMENT", "EXERCISES", "INCIDENT"],
}


def _norm(value: str, app_cfg: AppConfig) -> str:
    return normalize_category(
        str(value or ""),
        case_sensitive=getattr(app_cfg, "category_case_sensitive", False),
        trim_spaces=getattr(app_cfg, "category_trim_spaces", True),
    )


def family_of(parent_or_id: str) -> str:
    """Family prefix of a control id: 'BUSINESS_CONTINUITY.a' -> 'BUSINESS_CONTINUITY'."""
    return str(parent_or_id or "").split(".")[0].strip().upper()


def load_affinity_table(app_cfg: AppConfig) -> dict[str, list[str]]:
    """Built-in defaults overlaid with an optional human-reviewed JSON file."""
    table = {k.upper(): [f.upper() for f in v] for k, v in DEFAULT_AFFINITY.items()}
    path = getattr(app_cfg, "family_affinity_file", "") or ""
    if path and Path(path).exists():
        try:
            override = json.loads(Path(path).read_text(encoding="utf-8"))
            for key, families in override.items():
                if isinstance(families, list):
                    table[str(key).upper()] = [str(f).upper() for f in families]
        except Exception:
            pass  # a malformed table must never break a run — keep the defaults
    return table


def _source_category_keys(source: AtomicRequirement, app_cfg: AppConfig) -> set[str]:
    keys: set[str] = set()
    for value in [getattr(source, "primary_category", "") or source.category, source.category]:
        k = _norm(value, app_cfg)
        if k:
            keys.add(k)
    for value in getattr(source, "secondary_categories", []) or []:
        k = _norm(str(value), app_cfg)
        if k:
            keys.add(k)
    return keys


def _affine_families(source: AtomicRequirement, table: dict[str, list[str]]) -> set[str]:
    # Keyed by the CyFun function code (GV/PR/...) taken from the parent id.
    function = family_of(getattr(source, "parent_id", "") or source.atomic_id)
    return set(table.get(function, []))


def inject_affinity_candidates(
    source: AtomicRequirement,
    selected: list[CandidateScore],
    ranked_pool: list[CandidateScore],
    target_by_id: dict[str, AtomicRequirement],
    app_cfg: AppConfig,
    table: dict[str, list[str]],
    max_inject: int,
) -> tuple[list[CandidateScore], int]:
    """Append up to max_inject best-scoring affine candidates missing from `selected`.

    Returns (extended_selected, n_injected). An affine candidate is one that
    shares the source's ENISA category OR whose family is in the source's affine
    family set. `ranked_pool` must be sorted best-first (it is, coming from the
    scored candidate list).
    """
    if max_inject <= 0 or not ranked_pool:
        return selected, 0
    already = {s.candidate_id for s in selected}
    source_cats = _source_category_keys(source, app_cfg)
    affine_fams = _affine_families(source, table)
    if not source_cats and not affine_fams:
        return selected, 0

    injected: list[CandidateScore] = []
    for s in ranked_pool:
        if len(injected) >= max_inject:
            break
        if s.candidate_id in already:
            continue
        target = target_by_id.get(s.candidate_id)
        if target is None:
            continue
        tgt_cats = {_norm(getattr(target, "primary_category", "") or target.category, app_cfg)}
        for v in getattr(target, "secondary_categories", []) or []:
            tgt_cats.add(_norm(str(v), app_cfg))
        tgt_family = family_of(getattr(target, "parent_id", "") or target.atomic_id)
        if (source_cats & tgt_cats) or (tgt_family in affine_fams):
            s.affinity_injected = True  # tag for the payload/logs
            injected.append(s)
            already.add(s.candidate_id)

    return selected + injected, len(injected)
