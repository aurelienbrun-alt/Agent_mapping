from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Allow running from project root without installing the package.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import load_config
from src.azure_openai_client import AzureOpenAIClient
from src.cache import cache_dir, load_processed_cache
from src.category_taxonomy import repair_atoms_categories
from src.logging_utils import JsonlRunLogger


def _make_llm(cfg: object) -> AzureOpenAIClient:
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Repair ENISA categories in existing docs/cache without re-running atomization, fields or embeddings."
    )
    parser.add_argument("--env", default=".env", help=".env path relative to project root.")
    parser.add_argument("--framework", choices=["a", "b", "both"], default="both", help="Which framework cache to repair.")
    parser.add_argument("--only-low-confidence", action="store_true", help="Only repair atoms below CATEGORY_STRONG_CONFIDENCE_THRESHOLD.")
    parser.add_argument("--force", action="store_true", help="Ignore cached category decisions and recompute.")
    args = parser.parse_args()

    cfg = load_config(args.env)
    if args.only_low_confidence:
        object.__setattr__(cfg, "repair_only_low_confidence_categories", True)
    if args.force:
        object.__setattr__(cfg, "category_harmonization_force", True)

    logger = JsonlRunLogger(cfg.log_dir, "repair_categories")
    llm = _make_llm(cfg)

    frameworks = []
    if args.framework in {"a", "both"}:
        frameworks.append(cfg.framework_a)
    if args.framework in {"b", "both"}:
        frameworks.append(cfg.framework_b)

    for fw in frameworks:
        atoms = load_processed_cache(fw, cfg)
        if atoms is None:
            cdir = cache_dir(fw, cfg)
            print(f"No processed cache found for {fw.name}: {cdir}")
            print("Run the normal pipeline once first, or verify CACHE_KEY_MODE and framework file/name.")
            continue
        print(f"Repairing {fw.name}: {len(atoms)} atoms")
        repair_atoms_categories(atoms, fw, cfg, llm, logger, save_cache=True)
        print(f"Done: {fw.name}")

    print(f"Log file: {logger.jsonl_path}")
    print(f"Reports written in: {cfg.report_dir}")


if __name__ == "__main__":
    main()
