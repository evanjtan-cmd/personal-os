"""Thin infrastructure-only command-line interface."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from personal_os.config import get_database_path
from personal_os.database import initialize_database
from personal_os.errors import PersonalOSError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="personal-os")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init-db", help="initialize the configured SQLite database")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit status."""

    args = build_parser().parse_args(argv)

    try:
        if args.command == "init-db":
            database_path = get_database_path()
            version = initialize_database(database_path)
            print(f"Initialized database at {database_path} (schema version {version})")
            return 0
    except (PersonalOSError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    raise AssertionError(f"unhandled command: {args.command}")

