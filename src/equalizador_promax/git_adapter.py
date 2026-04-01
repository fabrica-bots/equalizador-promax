from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from equalizador_promax.errors import GitCommandError, ValidationError
from equalizador_promax.models import CandidateCommit, MergeRecord


@dataclass(frozen=True)
class CherryPickOutcome:
    status: str
    stdout: str
    stderr: str


class GitAdapter:
    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path.resolve()
        self.repo_root = self._discover_repo_root()

    @staticmethod
    def ensure_git_available() -> None:
        completed = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            raise ValidationError("Git is not available on PATH.")

    def get_git_dir(self) -> Path:
        git_dir = self._git("rev-parse", "--git-dir").stdout.strip()
        path = Path(git_dir)
        if not path.is_absolute():
            path = self.repo_root / path
        return path.resolve()

    def state_root(self) -> Path:
        return self.get_git_dir() / "equalizador-promax"

    def fetch_origin(self) -> None:
        self._git("fetch", "origin")

    def ensure_ref_exists(self, ref_name: str) -> None:
        self._git("rev-parse", "--verify", ref_name)

    def ensure_clean_working_tree(self) -> None:
        if self.status_porcelain().strip():
            raise ValidationError("Working tree is not clean.")

    def status_porcelain(self) -> str:
        return self._git("status", "--porcelain").stdout

    def current_branch_name(self) -> str | None:
        completed = self._git("branch", "--show-current", check=False)
        branch_name = completed.stdout.strip()
        return branch_name or None

    def is_cherry_pick_in_progress(self) -> bool:
        completed = self._git("rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD", check=False)
        return completed.returncode == 0

    def branch_exists(self, branch_name: str) -> bool:
        completed = self._git("rev-parse", "--verify", branch_name, check=False)
        return completed.returncode == 0

    def resolve_switch_target(self, ref_name: str) -> str:
        if ref_name.startswith("origin/"):
            local_branch = ref_name.split("/", 1)[1]
            if self.branch_exists(local_branch):
                return local_branch
        return ref_name

    def collect_merges(self, branch_name: str = "develop") -> list[MergeRecord]:
        completed = self._git(
            "log",
            branch_name,
            "--merges",
            "--first-parent",
            "--pretty=%H;%ct;%s",
        )
        merges: list[MergeRecord] = []
        for line in completed.stdout.splitlines():
            merge_hash, timestamp, subject = line.split(";", 2)
            merges.append(MergeRecord(merge_hash=merge_hash, timestamp=int(timestamp), subject=subject))
        return merges

    def get_merge_parents(self, merge_hash: str) -> tuple[str, str] | None:
        parents = self._git("show", "--pretty=%P", "-s", merge_hash).stdout.strip().split()
        if len(parents) < 2:
            return None
        return parents[0], parents[1]

    def list_branch_commits(
        self,
        first_parent: str,
        branch_parent: str,
        source_merge: str,
        source_keys: tuple[str, ...],
    ) -> list[CandidateCommit]:
        completed = self._git(
            "log",
            f"{first_parent}..{branch_parent}",
            "--no-merges",
            "--pretty=%H;%ct;%an;%s",
        )
        commits: list[CandidateCommit] = []
        normalized_source_keys = tuple(sorted(set(source_keys)))
        for line in completed.stdout.splitlines():
            commit_hash, timestamp, author, subject = line.split(";", 3)
            commits.append(
                CandidateCommit(
                    commit_hash=commit_hash,
                    timestamp=int(timestamp),
                    author=author,
                    subject=subject,
                    source_merge=source_merge,
                    source_keys=normalized_source_keys,
                )
            )
        return commits

    def create_equalization_branch(self, branch_name: str, base_ref: str = "origin/quality") -> None:
        existing = self._git("rev-parse", "--verify", branch_name, check=False)
        if existing.returncode == 0:
            raise ValidationError(f"Branch {branch_name} already exists.")
        self._git("switch", "-c", branch_name, base_ref)

    def cherry_pick(self, commit_hash: str) -> CherryPickOutcome:
        completed = self._git("cherry-pick", commit_hash, check=False)
        if completed.returncode == 0:
            return CherryPickOutcome(status="applied", stdout=completed.stdout, stderr=completed.stderr)
        if self.is_cherry_pick_in_progress():
            return CherryPickOutcome(status="conflict", stdout=completed.stdout, stderr=completed.stderr)
        raise GitCommandError(list(completed.args), completed.stderr, completed.stdout)

    def cherry_pick_continue(self) -> CherryPickOutcome:
        completed = self._git("cherry-pick", "--continue", check=False)
        if completed.returncode == 0:
            return CherryPickOutcome(status="applied", stdout=completed.stdout, stderr=completed.stderr)
        if self.is_cherry_pick_in_progress():
            return CherryPickOutcome(status="conflict", stdout=completed.stdout, stderr=completed.stderr)
        raise GitCommandError(list(completed.args), completed.stderr, completed.stdout)

    def cherry_pick_abort(self) -> None:
        if self.is_cherry_pick_in_progress():
            self._git("cherry-pick", "--abort")

    def switch(self, ref_name: str) -> None:
        self._git("switch", ref_name)

    def delete_branch(self, branch_name: str) -> None:
        self._git("branch", "-D", branch_name)

    def _discover_repo_root(self) -> Path:
        self.ensure_git_available()
        completed = self._git("rev-parse", "--show-toplevel")
        return Path(completed.stdout.strip()).resolve()

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if check and completed.returncode != 0:
            raise GitCommandError(list(completed.args), completed.stderr, completed.stdout)
        return completed
