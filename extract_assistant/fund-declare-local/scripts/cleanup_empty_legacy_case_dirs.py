#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "apps" / "api"))

from app.services import local_store  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete empty legacy case directories: accounts, identity, uploads."
    )
    parser.add_argument("--case-id", help="Only clean one case_id, for example case_008")
    args = parser.parse_args()

    case_ids = [args.case_id] if args.case_id else _list_case_ids()
    for case_id in case_ids:
        result = local_store.cleanup_empty_legacy_dirs(case_id)
        print(
            f"{case_id}: deleted={result['deleted_dirs']} skipped={result['skipped_dirs']}"
        )


def _list_case_ids() -> list[str]:
    data_root = local_store.get_data_root()
    if not data_root.exists():
        return []
    return sorted(
        path.name
        for path in data_root.iterdir()
        if path.is_dir() and path.name.startswith("case_")
    )


if __name__ == "__main__":
    main()
