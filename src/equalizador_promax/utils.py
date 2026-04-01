from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

ISSUE_KEY_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Z][A-Z0-9]+-\d+(?![A-Za-z0-9])")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify_repo_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "repo"


def generate_run_id(repo_name: str, now: datetime | None = None) -> str:
    instant = now or datetime.now()
    return f"{instant.strftime('%Y%m%d-%H%M%S')}-{slugify_repo_name(repo_name)}"


def calculate_fingerprint(
    repo_path: Path,
    story_keys: Iterable[str],
    *,
    source_ref: str = "origin/develop",
    target_ref: str = "origin/quality",
) -> str:
    normalized = [key.strip().upper() for key in story_keys if key.strip()]
    material = f"{repo_path.resolve()}|{source_ref}|{target_ref}|{','.join(sorted(set(normalized)))}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def extract_issue_keys(text: str) -> set[str]:
    return {match.group(0).upper() for match in ISSUE_KEY_PATTERN.finditer(text or "")}


def timestamp_to_iso_utc(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(microsecond=0).isoformat()


def sanitize_branch_component(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    normalized = re.sub(r"\s+", "_", normalized)
    normalized = re.sub(r"[^a-z0-9_]+", "-", normalized)
    normalized = re.sub(r"-+", "-", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    normalized = re.sub(r"_*-_*", "-", normalized)
    normalized = normalized.strip("-")
    return normalized or "equalizacao"


def build_release_branch_name(release_name: str, now: datetime | None = None) -> str:
    instant = now or datetime.now()
    suffix = instant.strftime("%d-%m-%Y-%H-%M-%S")
    return f"equalizacao/{sanitize_branch_component(release_name)}_{suffix}"
