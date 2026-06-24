from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import AtomicRequirement, MappingDecision
from .utils import stable_hash
from .logging_utils import JsonlRunLogger


def framework_atom_fingerprint(atoms: list[AtomicRequirement]) -> str:
    payload = [
        {
            "atomic_id": a.atomic_id,
            "parent_id": a.parent_id,
            "atomic_requirement": a.atomic_requirement,
            "parent_requirement": a.parent_requirement,
        }
        for a in sorted(atoms, key=lambda x: x.atomic_id)
    ]
    return stable_hash(payload)


def framework_parent_ids(atoms: list[AtomicRequirement]) -> set[str]:
    return {a.parent_id for a in atoms if a.parent_id}


def framework_atomic_ids(atoms: list[AtomicRequirement]) -> set[str]:
    return {a.atomic_id for a in atoms if a.atomic_id}


def validate_non_empty_framework(name: str, atoms: list[AtomicRequirement]) -> None:
    if not atoms:
        raise RuntimeError(f"No atomic requirements loaded for framework '{name}'. Check input file, column mapping and cache configuration.")


def print_preprocessing_summary(name_a: str, atoms_a: list[AtomicRequirement], name_b: str, atoms_b: list[AtomicRequirement]) -> None:
    print("\n=== Preprocessing summary ===", flush=True)
    print(f"- {name_a}: {len(atoms_a)} atomic requirement(s), {len(framework_parent_ids(atoms_a))} parent requirement(s)", flush=True)
    print(f"- {name_b}: {len(atoms_b)} atomic requirement(s), {len(framework_parent_ids(atoms_b))} parent requirement(s)", flush=True)


def validate_mapping_targets(
    decisions: list[MappingDecision],
    target_atoms: list[AtomicRequirement],
    *,
    direction: str,
    policy: str = "raise",
    logger: JsonlRunLogger | None = None,
) -> list[MappingDecision]:
    """Validate that all selected targets exist in the current target framework.

    This protects against stale mapping caches and stale framework caches. If the
    current run uses Test1_France.xlsx, the output must never contain controls
    from a previous full France cache.
    """
    atomic_ids = framework_atomic_ids(target_atoms)
    parent_ids = framework_parent_ids(target_atoms)
    invalid: list[dict[str, Any]] = []

    for d in decisions:
        bad_atomic = [tid for tid in (d.target_ids or []) if tid not in atomic_ids]
        bad_parent = [pid for pid in (d.target_parent_ids or []) if pid not in parent_ids and pid not in atomic_ids]
        if bad_atomic or bad_parent:
            invalid.append({
                "source_id": d.source_id,
                "bad_target_atomic_ids": bad_atomic,
                "bad_target_parent_ids": bad_parent,
                "selected_candidate_ids": d.selected_candidate_ids,
                "coverage_level": d.coverage_level,
            })

    if not invalid:
        if logger:
            logger.event("target_validation.done", direction=direction, invalid=0, decisions=len(decisions))
        return decisions

    if logger:
        logger.event("target_validation.invalid", direction=direction, invalid=len(invalid), sample=invalid[:20])

    policy = (policy or "raise").strip().lower()
    if policy in {"drop", "sanitize", "convert_to_gap"}:
        for d in decisions:
            valid_pairs = []
            for idx, tid in enumerate(d.target_ids or []):
                if tid in atomic_ids:
                    req = d.target_requirements[idx] if idx < len(d.target_requirements) else ""
                    valid_pairs.append((tid, req))
            if len(valid_pairs) != len(d.target_ids or []):
                if valid_pairs:
                    d.target_ids = [x[0] for x in valid_pairs]
                    d.selected_candidate_ids = list(d.target_ids)
                    d.target_requirements = [x[1] for x in valid_pairs]
                    d.target_parent_ids = [pid for pid in (d.target_parent_ids or []) if pid in parent_ids]
                    d.mapping_risk = "High"
                    d.gap = (d.gap + "\n" if d.gap else "") + "Stale target references were removed because they are not present in the current target framework input."
                else:
                    d.selected_candidate_ids = []
                    d.target_ids = []
                    d.target_requirements = []
                    d.target_parent_ids = []
                    d.target_parent_requirements = []
                    d.coverage_level = 0
                    d.equivalence_level = "Gap"
                    d.relation_type = "true_gap"
                    d.gap_type = "true_gap"
                    d.match_type = "None"
                    d.mapping_risk = "High"
                    d.gap = "Stale target references were removed; no selected target exists in the current target framework input."
        return decisions

    sample = "\n".join(str(x) for x in invalid[:10])
    raise RuntimeError(
        f"Invalid target IDs found in mapping direction {direction}. "
        "This usually means a stale framework cache or stale mapping_decisions_cache was reused. "
        "Delete docs/cache/mapping_decisions_cache.jsonl and ensure STRICT_INPUT_CACHE_VALIDATION=true. "
        f"Sample invalid references:\n{sample}"
    )
