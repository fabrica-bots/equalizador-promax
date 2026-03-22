from __future__ import annotations

import json
import re
from pathlib import Path

STATE_FILE_NAME = ".version-state.json"
VERSION_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)$")


def increment_patch_version(version: str) -> str:
    match = VERSION_PATTERN.fullmatch(version.strip())
    if not match:
        raise ValueError(f"Unsupported version format: {version}")
    major, minor, patch = (int(part) for part in match.groups())
    return f"{major}.{minor}.{patch + 1}"


def version_to_windows_tuple(version: str) -> tuple[int, int, int, int]:
    match = VERSION_PATTERN.fullmatch(version.strip())
    if not match:
        raise ValueError(f"Unsupported version format: {version}")
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch, 0


def read_current_version(project_root: Path) -> str:
    version_file = project_root / "src" / "equalizador_promax" / "version.py"
    content = version_file.read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', content)
    if not match:
        raise ValueError("Unable to read current version.")
    return match.group(1)


def write_version(project_root: Path, new_version: str) -> None:
    windows_tuple = version_to_windows_tuple(new_version)

    _write_regex(
        project_root / "src" / "equalizador_promax" / "version.py",
        r'__version__\s*=\s*"[^"]+"',
        f'__version__ = "{new_version}"',
    )
    _write_regex(
        project_root / "pyproject.toml",
        r'version\s*=\s*"[^"]+"',
        f'version = "{new_version}"',
    )
    _write_regex(
        project_root / "installer" / "EqualizadorProMax.iss",
        r'#define MyAppVersion ".*"',
        f'#define MyAppVersion "{new_version}"',
    )

    version_info_path = project_root / "installer" / "version-info.txt"
    version_info = version_info_path.read_text(encoding="utf-8")
    version_info = re.sub(r"filevers=\([^)]+\)", f"filevers={windows_tuple}", version_info)
    version_info = re.sub(r"prodvers=\([^)]+\)", f"prodvers={windows_tuple}", version_info)
    version_info = re.sub(
        r'StringStruct\("FileVersion", "[^"]+"\)',
        f'StringStruct("FileVersion", "{new_version}")',
        version_info,
    )
    version_info = re.sub(
        r'StringStruct\("ProductVersion", "[^"]+"\)',
        f'StringStruct("ProductVersion", "{new_version}")',
        version_info,
    )
    version_info_path.write_text(version_info, encoding="utf-8")


def save_version_state(project_root: Path, previous_version: str, new_version: str) -> Path:
    state_path = project_root / STATE_FILE_NAME
    payload = {
        "previous_version": previous_version,
        "current_version": new_version,
    }
    state_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return state_path


def load_version_state(project_root: Path) -> dict[str, str]:
    state_path = project_root / STATE_FILE_NAME
    if not state_path.exists():
        raise FileNotFoundError("No version state file found.")
    return json.loads(state_path.read_text(encoding="utf-8"))


def clear_version_state(project_root: Path) -> None:
    state_path = project_root / STATE_FILE_NAME
    if state_path.exists():
        state_path.unlink()


def _write_regex(path: Path, pattern: str, replacement: str) -> None:
    content = path.read_text(encoding="utf-8")
    updated = re.sub(pattern, replacement, content, count=1)
    path.write_text(updated, encoding="utf-8")
