from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from equalizador_promax.errors import InconsistentStateError
from equalizador_promax.models import RunManifest
from equalizador_promax.utils import timestamp_to_iso_utc, utc_now_iso

OPEN_RUN_STATUSES = {"initializing", "jira-ready", "commits-ready", "running", "paused"}


class RunStore:
    def __init__(self, state_root: Path) -> None:
        self.state_root = state_root
        self.runs_root = self.state_root / "runs"
        self.runs_root.mkdir(parents=True, exist_ok=True)

    def ensure_writable(self) -> None:
        self.runs_root.mkdir(parents=True, exist_ok=True)
        probe = self.runs_root / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()

    def run_dir(self, run_id: str) -> Path:
        return self.runs_root / run_id

    def create_run(self, manifest: RunManifest) -> Path:
        run_dir = self.run_dir(manifest.run_id)
        run_dir.mkdir(parents=True, exist_ok=False)
        self.write_manifest(manifest)
        return run_dir

    def write_manifest(self, manifest: RunManifest) -> None:
        manifest.updated_at = utc_now_iso()
        self._write_json(self.run_dir(manifest.run_id) / "manifest.json", manifest.to_dict())

    def load_manifest(self, run_id: str) -> RunManifest:
        path = self.run_dir(run_id) / "manifest.json"
        if not path.exists():
            raise InconsistentStateError(f"Run {run_id} not found.")
        return RunManifest.from_dict(self._read_json(path))

    def load_latest_manifest(self) -> RunManifest | None:
        manifests = self.list_manifests()
        return manifests[0] if manifests else None

    def find_open_run(self, fingerprint: str) -> RunManifest | None:
        for manifest in self.list_manifests():
            if manifest.fingerprint == fingerprint and manifest.status in OPEN_RUN_STATUSES:
                return manifest
        return None

    def find_latest_paused_run(self) -> RunManifest | None:
        for manifest in self.list_manifests():
            if manifest.status == "paused":
                return manifest
        return None

    def list_manifests(self) -> list[RunManifest]:
        manifests: list[RunManifest] = []
        for manifest_path in sorted(self.runs_root.glob("**/manifest.json"), reverse=True):
            manifests.append(RunManifest.from_dict(self._read_json(manifest_path)))
        manifests.sort(key=lambda item: item.created_at, reverse=True)
        return manifests

    def write_items(self, run_id: str, payload: dict[str, Any]) -> None:
        self._write_json(self.run_dir(run_id) / "items.json", payload)
        self.write_artifact_exports(run_id, payload)

    def load_items(self, run_id: str) -> dict[str, Any]:
        return self._read_json(self.run_dir(run_id) / "items.json")

    def update_commit_status(self, run_id: str, commit_hash: str, status: str) -> dict[str, Any]:
        payload = self.load_items(run_id)
        for commit in payload.get("commits", []):
            if commit.get("commit_hash") == commit_hash:
                commit["cherry_pick_status"] = status
                break
        self.write_items(run_id, payload)
        return payload

    def replace_items(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.write_items(run_id, payload)
        return payload

    def reset_commit_statuses(self, run_id: str, *, status: str = "pending") -> dict[str, Any]:
        payload = self.load_items(run_id)
        for commit in payload.get("commits", []):
            commit["cherry_pick_status"] = status
        self.write_items(run_id, payload)
        return payload

    def write_summary(self, run_id: str, content: str) -> None:
        (self.run_dir(run_id) / "summary.md").write_text(content, encoding="utf-8")

    def write_resume_hints(self, run_id: str, content: str) -> None:
        (self.run_dir(run_id) / "resume-hints.txt").write_text(content, encoding="utf-8")

    def journal(self, run_id: str) -> "ExecutionJournal":
        return ExecutionJournal(self.run_dir(run_id))

    def write_artifact_exports(self, run_id: str, payload: dict[str, Any]) -> None:
        run_dir = self.run_dir(run_id)
        self._write_stories_txt(run_dir / "stories.txt", payload)
        self._write_subtasks_txt(run_dir / "subtasks_por_story.txt", payload)
        self._write_commits_csv(run_dir / "commits.csv", payload)

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_stories_txt(self, path: Path, payload: dict[str, Any]) -> None:
        stories = payload.get("stories", [])
        lines = [self._format_story_line(story) for story in stories if story.get("key")]
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def _write_subtasks_txt(self, path: Path, payload: dict[str, Any]) -> None:
        eligible_items = payload.get("eligible_items", [])
        stories = [story for story in payload.get("stories", []) if story.get("key")]
        story_order = [story["key"] for story in stories]
        stories_by_key = {story["key"]: story for story in stories}
        subtasks_by_story: dict[str, list[str]] = {story_key: [] for story_key in story_order}

        for item in eligible_items:
            if item.get("item_type") != "subtask":
                continue
            parent_key = item.get("parent_key")
            key = item.get("key")
            if parent_key and key:
                subtasks_by_story.setdefault(parent_key, []).append(key)

        lines: list[str] = []
        for story_key in story_order:
            lines.append(self._format_story_line(stories_by_key[story_key]))
            story_subtasks = subtasks_by_story.get(story_key, [])
            if story_subtasks:
                lines.extend([f"- {subtask_key}" for subtask_key in story_subtasks])
            else:
                lines.append("- <sem subtasks>")
            lines.append("")

        if lines and not lines[-1]:
            lines.pop()
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def _format_story_line(self, story: dict[str, Any]) -> str:
        key = str(story.get("key", "")).strip()
        release_names = self._normalize_release_names(story.get("release_names", []))
        if not release_names:
            return key
        release_label = "Release" if len(release_names) == 1 else "Releases"
        return f"{key} [{release_label}: {', '.join(release_names)}]"

    def _normalize_release_names(self, raw_release_names: Any) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_release_name in raw_release_names or []:
            release_name = str(raw_release_name).strip()
            if not release_name or release_name in seen:
                continue
            normalized.append(release_name)
            seen.add(release_name)
        return normalized

    def _write_commits_csv(self, path: Path, payload: dict[str, Any]) -> None:
        commits = payload.get("commits", [])
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "commit_hash",
                    "commit_datetime_utc",
                    "author",
                    "subject",
                    "source_keys",
                    "cherry_pick_status",
                ],
            )
            writer.writeheader()
            for commit in commits:
                writer.writerow(
                    {
                        "commit_hash": commit.get("commit_hash", ""),
                        "commit_datetime_utc": timestamp_to_iso_utc(int(commit.get("timestamp", 0))),
                        "author": commit.get("author", ""),
                        "subject": commit.get("subject", ""),
                        "source_keys": ",".join(commit.get("source_keys", [])),
                        "cherry_pick_status": commit.get("cherry_pick_status", "pending"),
                    }
                )


class ExecutionJournal:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.events_path = run_dir / "events.jsonl"
        self.log_path = run_dir / "execution.log"

    def record(
        self,
        level: str,
        message: str,
        *,
        phase: str,
        item_key: str | None = None,
        commit_hash: str | None = None,
        action: str | None = None,
        result: str | None = None,
    ) -> None:
        timestamp = utc_now_iso()
        line = f"[{timestamp}] {level.upper():5} {message}"
        print(line)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

        event = {
            "timestamp": timestamp,
            "level": level,
            "phase": phase,
            "item_key": item_key,
            "commit_hash": commit_hash,
            "action": action,
            "result": result,
            "message": message,
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True) + "\n")
