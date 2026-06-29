"""Run the mapping pipeline programmatically.

Mirrors the orchestration in `run_agent.main()` but is driven by an injected
`AppConfig` (built from the UI selection) instead of argparse + `.env` framework
slots, and returns the in-memory decisions so the Baseline builder can reuse them
without re-running the mapping.

Reuses every `src/` stage unchanged — this module adds no mapping logic of its own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from src.config import AppConfig
from src.azure_openai_client import AzureOpenAIClient
from src.logging_utils import JsonlRunLogger
from src.preprocessing import process_framework
from src.matching import run_directional_mapping
from src.final_judge import run_final_judge
from src.parent_gap_synthesis import run_parent_gap_synthesis
from src.output_writer import write_mapping_workbook
from src.validation import validate_non_empty_framework, validate_mapping_targets
from src.models import MappingDecision
from src.utils import safe_filename

# Progress callback: receives a short human-readable stage label. No-op by default.
Progress = Callable[[str], None]


def _noop(_message: str) -> None:
    pass


@dataclass
class MappingRunResult:
    run_id: str
    cfg: AppConfig
    source_name: str
    target_name: str
    # Named seam: entity_types filters which requirements are in scope per framework.
    # Actual row-level filtering will be added here once each framework's entity-type
    # column is documented. For now the value is stored and surfaced in reports.
    entity_types: list[str]
    output_path: Path
    a_to_b: list[MappingDecision]
    b_to_a: list[MappingDecision] | None
    summary: dict[str, float | int] = field(default_factory=dict)


def _make_llm(cfg: AppConfig) -> AzureOpenAIClient:
    return AzureOpenAIClient(
        api_key=cfg.azure_openai_api_key,
        endpoint=cfg.azure_openai_endpoint,
        api_version=cfg.azure_openai_api_version,
        text_deployment=cfg.azure_openai_text_deployment,
        judge_deployment=cfg.azure_openai_judge_deployment,
        embedding_deployment=cfg.azure_openai_embedding_deployment,
        temperature=cfg.azure_openai_temperature,
        embedding_dimensions=cfg.azure_openai_embedding_dimensions,
        dry_run=cfg.dry_run_without_llm,
    )


def _map_one_direction(
    source_atoms,
    target_atoms,
    *,
    direction: str,
    target_framework: str,
    cfg: AppConfig,
    llm: AzureOpenAIClient,
    logger: JsonlRunLogger,
) -> list[MappingDecision]:
    decisions = run_directional_mapping(
        source_atoms, target_atoms, direction=direction, app_cfg=cfg, llm=llm, logger=logger
    )
    decisions = run_final_judge(decisions, cfg, llm, logger)
    if cfg.validate_output_target_ids:
        decisions = validate_mapping_targets(
            decisions, target_atoms, direction=direction, policy=cfg.invalid_target_id_policy, logger=logger
        )
    decisions = run_parent_gap_synthesis(
        decisions, direction=direction, target_framework=target_framework, app_cfg=cfg, llm=llm, logger=logger
    )
    return decisions


def _summary(a_to_b: list[MappingDecision], b_to_a: list[MappingDecision] | None) -> dict[str, float | int]:
    all_decisions = list(a_to_b) + list(b_to_a or [])
    total = len(all_decisions)
    avg = round(sum(d.coverage_level for d in all_decisions) / total, 1) if total else 0.0
    gaps = sum(1 for d in all_decisions if d.coverage_level == 0)
    return {
        "atomic_decisions": total,
        "average_coverage": avg,
        "gaps": gaps,
        "source_atoms": len(a_to_b),
        "target_atoms": len(b_to_a or []),
    }


def run_mapping(cfg: AppConfig, *, entity_types: list[str] | None = None, progress: Progress = _noop) -> MappingRunResult:
    a_name = cfg.framework_a.name
    b_name = cfg.framework_b.name
    run_id = f"web_{safe_filename(a_name)}_{safe_filename(b_name)}_{datetime.now():%Y-%m-%d_%H-%M-%S}"
    logger = JsonlRunLogger(cfg.log_dir, run_id)
    logger.event("run.start", framework_a=a_name, framework_b=b_name, source="webapp")
    llm = _make_llm(cfg)

    progress("Préparation des frameworks (atomisation, catégories, embeddings)…")
    atoms_a = process_framework(cfg.framework_a, cfg, llm, logger)
    atoms_b = process_framework(cfg.framework_b, cfg, llm, logger)
    validate_non_empty_framework(a_name, atoms_a)
    validate_non_empty_framework(b_name, atoms_b)

    progress(f"Mapping {a_name} → {b_name}…")
    a_to_b = _map_one_direction(
        atoms_a, atoms_b, direction=f"{a_name}->{b_name}", target_framework=b_name, cfg=cfg, llm=llm, logger=logger
    )

    b_to_a: list[MappingDecision] | None = None
    if cfg.bidirectional_mapping:
        progress(f"Mapping {b_name} → {a_name}…")
        b_to_a = _map_one_direction(
            atoms_b, atoms_a, direction=f"{b_name}->{a_name}", target_framework=a_name, cfg=cfg, llm=llm, logger=logger
        )

    progress("Génération du classeur Excel…")
    output_path = write_mapping_workbook(cfg, a_to_b, b_to_a, run_id)
    logger.event("run.done", output=str(output_path))

    return MappingRunResult(
        run_id=run_id,
        cfg=cfg,
        source_name=a_name,
        target_name=b_name,
        entity_types=entity_types or ["essential", "important"],
        output_path=Path(output_path),
        a_to_b=a_to_b,
        b_to_a=b_to_a,
        summary=_summary(a_to_b, b_to_a),
    )
