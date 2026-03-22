from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class JiraItem:
    key: str
    parent_key: str | None
    item_type: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MergeRecord:
    merge_hash: str
    timestamp: int
    subject: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateCommit:
    commit_hash: str
    timestamp: int
    author: str
    subject: str
    source_merge: str
    source_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "commit_hash": self.commit_hash,
            "timestamp": self.timestamp,
            "author": self.author,
            "subject": self.subject,
            "source_merge": self.source_merge,
            "source_keys": list(self.source_keys),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CandidateCommit":
        return cls(
            commit_hash=payload["commit_hash"],
            timestamp=int(payload["timestamp"]),
            author=payload["author"],
            subject=payload["subject"],
            source_merge=payload["source_merge"],
            source_keys=tuple(payload.get("source_keys", [])),
        )


@dataclass
class RunManifest:
    run_id: str
    repo_path: str
    repo_slug: str
    branch_name: str
    input_stories: list[str]
    release_id: str | None
    release_name: str | None
    fingerprint: str
    status: str
    phase: str
    current_commit_index: int
    total_commits: int
    applied_commit_count: int
    conflict_count: int
    created_at: str
    updated_at: str
    source_ref: str = "origin/develop"
    target_ref: str = "origin/quality"
    paused_reason: str | None = None
    conflict_commit: str | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RunManifest":
        return cls(
            run_id=payload["run_id"],
            repo_path=payload["repo_path"],
            repo_slug=payload["repo_slug"],
            branch_name=payload["branch_name"],
            source_ref=payload.get("source_ref", "origin/develop"),
            target_ref=payload.get("target_ref", "origin/quality"),
            input_stories=list(payload["input_stories"]),
            release_id=payload.get("release_id"),
            release_name=payload.get("release_name"),
            fingerprint=payload["fingerprint"],
            status=payload["status"],
            phase=payload["phase"],
            current_commit_index=int(payload["current_commit_index"]),
            total_commits=int(payload["total_commits"]),
            applied_commit_count=int(payload.get("applied_commit_count", 0)),
            conflict_count=int(payload.get("conflict_count", 0)),
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            paused_reason=payload.get("paused_reason"),
            conflict_commit=payload.get("conflict_commit"),
            last_error=payload.get("last_error"),
        )


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    details: str
