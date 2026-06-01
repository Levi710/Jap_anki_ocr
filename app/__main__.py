from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .profiling import create_profiling_run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app")
    subparsers = parser.add_subparsers(dest="command", required=True)

    profile_parser = subparsers.add_parser("profile", help="Create a Phase 1.5 profiling run")
    profile_parser.add_argument("pdf_path", help="Path to input PDF")
    profile_parser.add_argument(
        "--runs-dir",
        default="runs",
        help="Output root for profiling runs (default: runs)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "profile":
        pdf_path = Path(args.pdf_path)
        if not pdf_path.exists():
            parser.error(f"PDF does not exist: {pdf_path}")

        run_dir = create_profiling_run(pdf_path=pdf_path, runs_root=Path(args.runs_dir))
        print(f"Profiling run created: {run_dir}")
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
