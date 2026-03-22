from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from equalizador_promax.versioning import (  # noqa: E402
    clear_version_state,
    increment_patch_version,
    load_version_state,
    read_current_version,
    save_version_state,
    write_version,
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="version-tool")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("show")
    subparsers.add_parser("bump")
    subparsers.add_parser("rollback")
    args = parser.parse_args()

    if args.command == "show":
        print(read_current_version(PROJECT_ROOT))
        return 0

    if args.command == "bump":
        current_version = read_current_version(PROJECT_ROOT)
        new_version = increment_patch_version(current_version)
        write_version(PROJECT_ROOT, new_version)
        save_version_state(PROJECT_ROOT, current_version, new_version)
        print(new_version)
        return 0

    if args.command == "rollback":
        state = load_version_state(PROJECT_ROOT)
        previous_version = state["previous_version"]
        current_version = read_current_version(PROJECT_ROOT)
        write_version(PROJECT_ROOT, previous_version)
        clear_version_state(PROJECT_ROOT)
        print(f"{current_version} -> {previous_version}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
