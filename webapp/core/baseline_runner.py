"""Build a group baseline from a completed mapping.

A baseline is the consolidated set of control points required to be compliant across
the selected frameworks, restricted to the chosen ENISA categories (domains). It
reuses the existing consolidation step (`run_consolidated_framework`) on the
decisions kept in memory from the mapping run — i.e. *map first, then build baseline*.

v1 consolidates the single source→target pair. The same shape extends to 1→many
later: aggregate decisions from several target directions before consolidation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.logging_utils import JsonlRunLogger
from src.consolidated_framework import run_consolidated_framework, ConsolidatedRequirement
from src.consolidated_output_writer import write_consolidated_workbook
from src.models import MappingDecision

from .categories import category_match_key
from .pipeline_runner import MappingRunResult, _make_llm

Progress = Callable[[str], None]


def _noop(_message: str) -> None:
    pass


@dataclass
class BaselineResult:
    output_path: Path
    items: list[ConsolidatedRequirement]
    selected_categories: list[str]
    summary: dict[str, int] = field(default_factory=dict)


def _filter_by_categories(
    decisions: list[MappingDecision], selected_keys: set[str]
) -> list[MappingDecision]:
    if not selected_keys:
        return list(decisions)
    return [d for d in decisions if category_match_key(d.source_category) in selected_keys]


def build_baseline(
    mapping: MappingRunResult,
    selected_categories: list[str],
    *,
    progress: Progress = _noop,
) -> BaselineResult:
    cfg = mapping.cfg
    selected_keys = {category_match_key(c) for c in selected_categories if c}

    progress("Filtrage des décisions par catégorie ENISA…")
    a_to_b = _filter_by_categories(mapping.a_to_b, selected_keys)
    b_to_a = _filter_by_categories(mapping.b_to_a, selected_keys) if mapping.b_to_a is not None else None

    logger = JsonlRunLogger(cfg.log_dir, f"{mapping.run_id}_baseline")
    llm = _make_llm(cfg)

    progress("Consolidation des points de contrôle…")
    items = run_consolidated_framework(a_to_b, b_to_a, cfg, llm, logger)

    progress("Génération du classeur baseline…")
    output_path = write_consolidated_workbook(cfg, items, mapping.run_id)
    logger.event("baseline.done", output=str(output_path), items=len(items))

    origins: dict[str, int] = {}
    for item in items:
        origins[item.origin] = origins.get(item.origin, 0) + 1

    return BaselineResult(
        output_path=Path(output_path),
        items=items,
        selected_categories=list(selected_categories),
        summary={"total": len(items), **origins},
    )
