from __future__ import annotations

import argparse
from pathlib import Path

from src.config import load_config
from src.log_analyzer import analyze_log_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze a JSONL run log and generate a Markdown report.")
    parser.add_argument("log_file", help="Path to logs/<run_id>.jsonl")
    args = parser.parse_args()
    cfg = load_config()
    report = analyze_log_file(Path(args.log_file), cfg.report_dir)
    print(f"Report generated: {report}")


if __name__ == "__main__":
    main()
