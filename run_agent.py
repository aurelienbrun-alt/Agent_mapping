from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# Auto-activate the project virtual environment on Windows when the script is
# run with the system Python (e.g. double-click or bare `python run_agent.py`).
# The check is intentionally early — before any third-party imports — so that
# even packages like `dotenv` that live only in the venv are found.
# ---------------------------------------------------------------------------
def _relaunch_in_venv() -> None:
    root = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(root, ".venv", "Scripts", "python.exe")
    if not os.path.exists(venv_python):
        return  # no venv found, proceed and let the import error surface naturally
    if os.path.abspath(sys.executable).lower() == os.path.abspath(venv_python).lower():
        return  # already running inside the venv — no infinite loop
    import subprocess
    sys.exit(subprocess.run([venv_python] + sys.argv).returncode)


_relaunch_in_venv()

import argparse
import re
from datetime import datetime
from time import perf_counter

# Ensure UTF-8 output on Windows terminals that default to cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src.config import load_config, validate_config
from src.final_judge import run_final_judge
from src.guideline_rag import GuidelineIndex
from src.azure_openai_client import AzureOpenAIClient
from src.log_analyzer import analyze_log_file
from src.logging_utils import JsonlRunLogger
from src.matching import run_directional_mapping
from src.parent_gap_synthesis import run_parent_gap_synthesis
from src.output_writer import write_mapping_workbook
from src.consolidated_framework import run_consolidated_framework
from src.consolidated_output_writer import write_consolidated_workbook
from src.preprocessing import process_framework
from src.validation import validate_non_empty_framework, print_preprocessing_summary, validate_mapping_targets
from src.cache import cache_dir
from src.utils import safe_filename


def _stage(label: str) -> float:
    print(f"\n=== {label} ===", flush=True)
    return perf_counter()


def _done(label: str, start: float) -> None:
    elapsed = perf_counter() - start
    print(f"✓ {label} completed in {elapsed:.1f}s", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run enterprise Azure OpenAI regulatory framework mapping.")
    parser.add_argument("--env", default=".env", help="Path to .env file, relative to project root by default.")
    args = parser.parse_args()

    cfg = load_config(args.env)
    # Validate configuration early. Blocking inconsistencies raise here, before any
    # logger/cache/LLM work. Non-blocking warnings are collected and logged below.
    config_warnings = validate_config(cfg)
    run_id = f"run_{safe_filename(cfg.framework_a.name)}_{safe_filename(cfg.framework_b.name)}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
    logger = JsonlRunLogger(cfg.log_dir, run_id)
    for w in config_warnings:
        print(f"[CONFIG WARNING] {w}", flush=True)
        logger.event("config.warning", message=w)
    logger.event("run.start", framework_a=cfg.framework_a.name, framework_b=cfg.framework_b.name)

    try:
        llm = AzureOpenAIClient(
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
        logger.event(
            "llm.provider",
            provider="azure_openai",
            text_deployment=cfg.azure_openai_text_deployment,
            judge_deployment=cfg.azure_openai_judge_deployment,
            category_deployment=cfg.azure_openai_category_deployment,
            embedding_deployment=cfg.azure_openai_embedding_deployment,
        )

        # --- Guideline RAG index (optional) ---
        guideline_a = guideline_b = None
        if cfg.use_guideline_rag:
            print("\n=== Guideline RAG index ===", flush=True)
            guideline_a = GuidelineIndex(
                cfg.framework_a.name, cfg.guideline_dir, cfg.docs_cache_dir, llm,
                chunk_size=cfg.guideline_chunk_size, chunk_overlap=cfg.guideline_chunk_overlap,
            )
            found_a = guideline_a.load_or_build()
            if not found_a:
                print(f"  [Guideline RAG] No guideline file found for '{cfg.framework_a.name}' — RAG disabled for this framework.", flush=True)
                guideline_a = None
            if cfg.bidirectional_mapping:
                guideline_b = GuidelineIndex(
                    cfg.framework_b.name, cfg.guideline_dir, cfg.docs_cache_dir, llm,
                    chunk_size=cfg.guideline_chunk_size, chunk_overlap=cfg.guideline_chunk_overlap,
                )
                found_b = guideline_b.load_or_build()
                if not found_b:
                    print(f"  [Guideline RAG] No guideline file found for '{cfg.framework_b.name}' — RAG disabled for this framework.", flush=True)
                    guideline_b = None

        t = _stage("[1/6] Preprocessing and cache loading")
        print(f"Source A: {cfg.framework_a.name} | file={cfg.framework_a.file} | cache={cache_dir(cfg.framework_a, cfg)}", flush=True)
        print(f"Source B: {cfg.framework_b.name} | file={cfg.framework_b.file} | cache={cache_dir(cfg.framework_b, cfg)}", flush=True)
        atoms_a = process_framework(cfg.framework_a, cfg, llm, logger)
        atoms_b = process_framework(cfg.framework_b, cfg, llm, logger)
        validate_non_empty_framework(cfg.framework_a.name, atoms_a)
        validate_non_empty_framework(cfg.framework_b.name, atoms_b)
        print_preprocessing_summary(cfg.framework_a.name, atoms_a, cfg.framework_b.name, atoms_b)
        _done("Preprocessing and cache loading", t)

        t = _stage(f"[2/6] Directional mapping: {cfg.framework_a.name} -> {cfg.framework_b.name}")
        a_to_b = run_directional_mapping(
            atoms_a,
            atoms_b,
            direction=f"{cfg.framework_a.name}->{cfg.framework_b.name}",
            app_cfg=cfg,
            llm=llm,
            logger=logger,
            guideline_index=guideline_a,
        )
        _done(f"Directional mapping: {cfg.framework_a.name} -> {cfg.framework_b.name}", t)
        t = _stage(f"[3/6] Final judge: {cfg.framework_a.name} -> {cfg.framework_b.name}")
        a_to_b = run_final_judge(a_to_b, cfg, llm, logger)
        _done(f"Final judge: {cfg.framework_a.name} -> {cfg.framework_b.name}", t)
        if cfg.validate_output_target_ids:
            print("Validating target IDs for current target framework...", flush=True)
            a_to_b = validate_mapping_targets(a_to_b, atoms_b, direction=f"{cfg.framework_a.name}->{cfg.framework_b.name}", policy=cfg.invalid_target_id_policy, logger=logger)

        t = _stage(f"[4/6] Parent gap synthesis: {cfg.framework_a.name} -> {cfg.framework_b.name}")
        a_to_b = run_parent_gap_synthesis(
            a_to_b,
            direction=f"{cfg.framework_a.name}->{cfg.framework_b.name}",
            target_framework=cfg.framework_b.name,
            app_cfg=cfg,
            llm=llm,
            logger=logger,
        )
        _done(f"Parent gap synthesis: {cfg.framework_a.name} -> {cfg.framework_b.name}", t)

        b_to_a = None
        if cfg.bidirectional_mapping:
            t = _stage(f"[2/6] Directional mapping: {cfg.framework_b.name} -> {cfg.framework_a.name}")
            b_to_a = run_directional_mapping(
                atoms_b,
                atoms_a,
                direction=f"{cfg.framework_b.name}->{cfg.framework_a.name}",
                app_cfg=cfg,
                llm=llm,
                logger=logger,
                guideline_index=guideline_b,
            )
            _done(f"Directional mapping: {cfg.framework_b.name} -> {cfg.framework_a.name}", t)
            t = _stage(f"[3/6] Final judge: {cfg.framework_b.name} -> {cfg.framework_a.name}")
            b_to_a = run_final_judge(b_to_a, cfg, llm, logger)
            _done(f"Final judge: {cfg.framework_b.name} -> {cfg.framework_a.name}", t)
            if cfg.validate_output_target_ids:
                print("Validating target IDs for current target framework...", flush=True)
                b_to_a = validate_mapping_targets(b_to_a, atoms_a, direction=f"{cfg.framework_b.name}->{cfg.framework_a.name}", policy=cfg.invalid_target_id_policy, logger=logger)

            t = _stage(f"[4/6] Parent gap synthesis: {cfg.framework_b.name} -> {cfg.framework_a.name}")
            b_to_a = run_parent_gap_synthesis(
                b_to_a,
                direction=f"{cfg.framework_b.name}->{cfg.framework_a.name}",
                target_framework=cfg.framework_a.name,
                app_cfg=cfg,
                llm=llm,
                logger=logger,
            )
            _done(f"Parent gap synthesis: {cfg.framework_b.name} -> {cfg.framework_a.name}", t)
        else:
            logger.event("bidirectional.skip", reason="BIDIRECTIONAL_MAPPING=false")

        if cfg.run_consolidated_framework:
            t = _stage("[4.5/6] Generating consolidated framework")
            consolidated = run_consolidated_framework(a_to_b, b_to_a, cfg, llm, logger)
            if consolidated:
                cons_path = write_consolidated_workbook(cfg, consolidated, run_id)
                logger.event("consolidated.write", output=str(cons_path))
                print(f"Consolidated framework: {cons_path}", flush=True)
            _done("Generating consolidated framework", t)

        criticality_map: dict[str, dict[str, bool]] = {}
        if cfg.enable_entity_criticality:
            for atom in list(atoms_a) + list(atoms_b):
                pid = re.sub(r"__row_\d+$", "", str(getattr(atom, "parent_id", "") or ""))
                if pid and pid not in criticality_map:
                    criticality_map[pid] = {
                        "essential": bool(getattr(atom, "essential", True)),
                        "important": bool(getattr(atom, "important", False)),
                    }
            logger.event("entity_criticality.map", entries=len(criticality_map))

        t = _stage("[5/6] Writing Excel workbook")
        output_path = write_mapping_workbook(cfg, a_to_b, b_to_a, run_id, criticality=criticality_map, llm=llm, logger=logger)
        _done("Writing Excel workbook", t)
        logger.event("output.write", output=str(output_path))
        t = _stage("[6/6] Writing log analysis report")
        report_path = analyze_log_file(logger.jsonl_path, cfg.report_dir)
        _done("Writing log analysis report", t)
        logger.event("report.write", report=str(report_path))
        logger.event("run.done", output=str(output_path), report=str(report_path))

        print(f"Output workbook: {output_path}")
        print(f"Log file: {logger.jsonl_path}")
        print(f"Log analysis: {report_path}")
    except Exception as exc:
        logger.error("run.failed", exc)
        raise


if __name__ == "__main__":
    main()
