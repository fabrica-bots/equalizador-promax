from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from equalizador_promax.config import AppConfig, load_config
from equalizador_promax.correlation import (
    consolidate_items,
    deduplicate_commits,
    find_unmatched_item_keys,
    match_merge_to_items,
    normalize_release_ids,
    normalize_story_keys,
)
from equalizador_promax.errors import ConflictPauseError, InconsistentStateError, ValidationError
from equalizador_promax.git_adapter import GitAdapter
from equalizador_promax.jira_client import JiraClient
from equalizador_promax.models import CandidateCommit, DoctorCheck, JiraItem, ReleaseReference, RunManifest
from equalizador_promax.run_store import ExecutionJournal, RunStore
from equalizador_promax.utils import build_release_branch_name, calculate_fingerprint, generate_run_id, utc_now_iso


class EqualizadorService:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        self.jira = JiraClient(self.config.jira)

    def doctor(
        self,
        repo_path: Path,
        *,
        source_ref: str = "origin/develop",
        target_ref: str = "origin/quality",
    ) -> list[DoctorCheck]:
        checks: list[DoctorCheck] = []

        try:
            GitAdapter.ensure_git_available()
            checks.append(DoctorCheck(name="git-cli", ok=True, details="Git encontrado no PATH."))
        except Exception as exc:
            checks.append(DoctorCheck(name="git-cli", ok=False, details=str(exc)))
            return checks

        try:
            git = GitAdapter(repo_path)
            checks.append(DoctorCheck(name="git-repo", ok=True, details=f"Repositorio valido: {git.repo_root}"))
        except Exception as exc:
            checks.append(DoctorCheck(name="git-repo", ok=False, details=str(exc)))
            return checks

        for ref_name in (source_ref, target_ref):
            try:
                git.ensure_ref_exists(ref_name)
                checks.append(DoctorCheck(name=f"git-ref:{ref_name}", ok=True, details=f"Ref {ref_name} acessivel."))
            except Exception as exc:
                checks.append(DoctorCheck(name=f"git-ref:{ref_name}", ok=False, details=str(exc)))

        try:
            git.ensure_clean_working_tree()
            checks.append(DoctorCheck(name="working-tree", ok=True, details="Working tree limpo."))
        except Exception as exc:
            checks.append(DoctorCheck(name="working-tree", ok=False, details=str(exc)))

        try:
            store = RunStore(git.state_root())
            store.ensure_writable()
            checks.append(DoctorCheck(name="state-store", ok=True, details=f"Diretorio de estado pronto em {store.state_root}"))
        except Exception as exc:
            checks.append(DoctorCheck(name="state-store", ok=False, details=str(exc)))

        try:
            self.jira.validate_configuration()
            checks.append(DoctorCheck(name="jira-config", ok=True, details="Configuracao basica do Jira valida."))
        except Exception as exc:
            checks.append(DoctorCheck(name="jira-config", ok=False, details=str(exc)))

        if self.jira.has_secret():
            checks.append(DoctorCheck(name="jira-secret", ok=True, details="Segredo do Jira encontrado."))
        else:
            checks.append(DoctorCheck(name="jira-secret", ok=False, details="Segredo do Jira nao encontrado."))

        if all(check.ok for check in checks if check.name in {"jira-config", "jira-secret"}):
            try:
                self.jira.validate_connectivity()
                checks.append(DoctorCheck(name="jira-connectivity", ok=True, details="Conectividade com Jira validada."))
            except Exception as exc:
                checks.append(DoctorCheck(name="jira-connectivity", ok=False, details=str(exc)))

        return checks

    def run(
        self,
        repo_path: Path,
        story_keys: list[str],
        release_refs: list[ReleaseReference] | None = None,
        story_release_map: dict[str, list[ReleaseReference]] | None = None,
        *,
        force_new: bool = False,
        release_id: str | None = None,
        release_name: str | None = None,
        source_ref: str = "origin/develop",
        target_ref: str = "origin/quality",
    ) -> RunManifest:
        manifest = self.capture_jira_snapshot(
            repo_path,
            story_keys,
            release_refs=release_refs,
            story_release_map=story_release_map,
            force_new=force_new,
            release_id=release_id,
            release_name=release_name,
            source_ref=source_ref,
            target_ref=target_ref,
        )
        manifest = self.fetch_commits(repo_path, manifest.run_id)
        return self.apply_cherry_picks(repo_path, manifest.run_id)

    def capture_jira_snapshot(
        self,
        repo_path: Path,
        story_keys: list[str],
        release_refs: list[ReleaseReference] | None = None,
        story_release_map: dict[str, list[ReleaseReference]] | None = None,
        *,
        force_new: bool = False,
        release_id: str | None = None,
        release_name: str | None = None,
        source_ref: str = "origin/develop",
        target_ref: str = "origin/quality",
    ) -> RunManifest:
        normalized_stories = normalize_story_keys(story_keys)
        if not normalized_stories:
            raise ValidationError("At least one story key must be informed.")

        normalized_release_refs = list(release_refs or [])
        normalized_story_release_map = {key: list(references) for key, references in (story_release_map or {}).items()}
        release_id = release_id or ",".join(reference.release_id for reference in normalized_release_refs) or None
        release_name = release_name or ", ".join(reference.release_name for reference in normalized_release_refs) or None

        git = GitAdapter(repo_path)
        store = RunStore(git.state_root())
        store.ensure_writable()
        fingerprint = calculate_fingerprint(
            git.repo_root,
            normalized_stories,
            source_ref=source_ref,
            target_ref=target_ref,
        )
        existing = store.find_open_run(fingerprint)
        if existing and not force_new:
            raise InconsistentStateError(
                f"Existing unfinished run detected ({existing.run_id}). Use discard/resume or --force-new."
            )

        manifest = self._create_manifest(
            git,
            store,
            normalized_stories,
            normalized_release_refs,
            release_id=release_id,
            release_name=release_name,
            fingerprint=fingerprint,
            source_ref=source_ref,
            target_ref=target_ref,
        )
        journal = store.journal(manifest.run_id)
        journal.record("info", "Starting Jira snapshot capture.", phase="jira", action="jira-start", result="ok")

        items_payload: dict[str, Any] | None = None
        try:
            items_payload = self._build_jira_snapshot(
                normalized_stories,
                journal,
                story_release_map=normalized_story_release_map,
            )
            store.replace_items(manifest.run_id, items_payload)
            manifest.status = "jira-ready"
            manifest.phase = "jira-ready"
            manifest.last_error = None
            store.write_manifest(manifest)
            store.write_summary(manifest.run_id, self._render_summary(manifest, items_payload))
            journal.record(
                "info",
                f"Jira snapshot captured with {items_payload['stats']['eligible_item_count']} eligible items.",
                phase="jira",
                action="jira-finish",
                result="ok",
            )
            return manifest
        except Exception as exc:
            self._mark_failed(store, manifest, items_payload, exc)
            raise

    def fetch_commits(self, repo_path: Path, run_id: str | None = None) -> RunManifest:
        git = GitAdapter(repo_path)
        manifest, store, items_payload = self._load_manifest_with_items(git, run_id)

        if git.is_cherry_pick_in_progress():
            raise InconsistentStateError(
                "A cherry-pick is in progress. Use resume or discard the current branch before recalculating commits."
            )
        if git.branch_exists(manifest.branch_name):
            raise InconsistentStateError(
                f"Branch {manifest.branch_name} already exists. Discard the current branch before recalculating commits."
            )

        git.fetch_origin()
        git.ensure_ref_exists(manifest.source_ref)

        journal = store.journal(manifest.run_id)
        journal.record("info", "Starting commit discovery from cached Jira items.", phase="planning", action="plan-start", result="ok")

        try:
            items_payload, commit_plan = self._build_commit_plan(
                items_payload,
                git,
                journal,
                source_ref=manifest.source_ref,
            )
            manifest.total_commits = len(commit_plan)
            manifest.current_commit_index = 0
            manifest.applied_commit_count = 0
            manifest.conflict_count = 0
            manifest.status = "commits-ready"
            manifest.phase = "commits-ready"
            manifest.paused_reason = None
            manifest.conflict_commit = None
            manifest.last_error = None
            store.replace_items(manifest.run_id, items_payload)
            store.write_manifest(manifest)
            store.write_summary(manifest.run_id, self._render_summary(manifest, items_payload))
            journal.record(
                "info",
                f"Commit discovery finished with {len(commit_plan)} distinct commits.",
                phase="planning",
                action="plan-finish",
                result="ok",
            )
            return manifest
        except Exception as exc:
            self._mark_failed(store, manifest, items_payload, exc)
            raise

    def apply_cherry_picks(self, repo_path: Path, run_id: str | None = None) -> RunManifest:
        git = GitAdapter(repo_path)
        manifest, store, items_payload = self._load_manifest_with_items(git, run_id)
        commit_plan = [CandidateCommit.from_dict(item) for item in items_payload.get("commits", [])]
        if not commit_plan:
            raise InconsistentStateError("No commit list captured for this run. Execute fetch-commits first.")
        if manifest.status == "paused":
            raise InconsistentStateError(f"Run {manifest.run_id} is paused. Use resume or discard the current branch first.")
        if manifest.phase != "commits-ready":
            raise InconsistentStateError(
                f"Run {manifest.run_id} is not ready for cherry-picks. Execute fetch-commits before applying."
            )
        if git.is_cherry_pick_in_progress():
            raise InconsistentStateError("A cherry-pick is already in progress. Use resume or discard the current branch.")

        git.fetch_origin()
        git.ensure_ref_exists(manifest.target_ref)
        git.ensure_clean_working_tree()

        journal = store.journal(manifest.run_id)
        try:
            git.create_equalization_branch(manifest.branch_name, base_ref=manifest.target_ref)
            journal.record(
                "info",
                f"Created branch {manifest.branch_name} from {manifest.target_ref}.",
                phase="branching",
                action="branch-create",
                result="ok",
            )
            manifest.status = "running"
            manifest.phase = "applying"
            manifest.current_commit_index = 0
            manifest.applied_commit_count = 0
            manifest.conflict_count = 0
            manifest.paused_reason = None
            manifest.conflict_commit = None
            manifest.last_error = None
            items_payload = store.reset_commit_statuses(manifest.run_id)
            store.write_manifest(manifest)
            return self._apply_commit_plan(store, journal, git, manifest, commit_plan, items_payload)
        except Exception as exc:
            self._mark_failed(store, manifest, items_payload, exc)
            raise

    def discard_current_branch(self, repo_path: Path, run_id: str | None = None) -> RunManifest:
        git = GitAdapter(repo_path)
        manifest, store, items_payload = self._load_manifest_with_items(git, run_id)
        commit_plan = [CandidateCommit.from_dict(item) for item in items_payload.get("commits", [])]
        if not commit_plan:
            raise InconsistentStateError("No commit list captured for this run. Execute fetch-commits before discarding.")

        journal = store.journal(manifest.run_id)
        git.ensure_ref_exists(manifest.source_ref)
        git.cherry_pick_abort()
        current_branch = git.current_branch_name()
        if current_branch == manifest.branch_name:
            git.switch(git.resolve_switch_target(manifest.source_ref))
        if git.branch_exists(manifest.branch_name):
            git.delete_branch(manifest.branch_name)

        items_payload = store.reset_commit_statuses(manifest.run_id)
        manifest.status = "commits-ready"
        manifest.phase = "commits-ready"
        manifest.current_commit_index = 0
        manifest.applied_commit_count = 0
        manifest.conflict_count = 0
        manifest.paused_reason = None
        manifest.conflict_commit = None
        manifest.last_error = None
        store.write_manifest(manifest)
        store.write_summary(manifest.run_id, self._render_summary(manifest, items_payload))
        journal.record(
            "info",
            f"Discarded branch {manifest.branch_name} and returned to {manifest.source_ref}.",
            phase="discard",
            action="branch-discard",
            result="ok",
        )
        return manifest

    def resolve_story_keys(self, story_keys: list[str] | None = None) -> list[str]:
        normalized = normalize_story_keys(story_keys or [])
        if not normalized:
            raise ValidationError("At least one story key must be informed.")
        return normalized

    def resolve_inputs(
        self,
        release_ids: list[str] | None = None,
        story_keys: list[str] | None = None,
    ) -> tuple[list[str], list[ReleaseReference], dict[str, list[ReleaseReference]]]:
        normalized_release_ids = normalize_release_ids(release_ids or [])
        normalized_manual_stories = normalize_story_keys(story_keys or [])
        if not normalized_release_ids and not normalized_manual_stories:
            raise ValidationError("At least one release id or story key must be informed.")

        combined_story_keys: list[str] = []
        seen_story_keys: set[str] = set()
        release_refs: list[ReleaseReference] = []
        story_release_map: dict[str, list[ReleaseReference]] = {}

        for release_id in normalized_release_ids:
            release_story_keys, release_name = self.resolve_release(release_id)
            release_ref = ReleaseReference(release_id=release_id, release_name=release_name)
            release_refs.append(release_ref)
            for story_key in release_story_keys:
                story_release_map.setdefault(story_key, []).append(release_ref)
                if story_key in seen_story_keys:
                    continue
                combined_story_keys.append(story_key)
                seen_story_keys.add(story_key)

        for story_key in normalized_manual_stories:
            if story_key in seen_story_keys:
                continue
            combined_story_keys.append(story_key)
            seen_story_keys.add(story_key)

        return combined_story_keys, release_refs, story_release_map

    def resolve_release(self, release_id: str) -> tuple[list[str], str]:
        release_name = self.jira.fetch_release_name(release_id)
        issue_keys = self.jira.fetch_release_issue_keys(release_id)
        normalized = normalize_story_keys(issue_keys)
        if not normalized:
            raise ValidationError(f"No top-level Jira items found for release id {release_id}.")
        return normalized, release_name

    def resume(self, repo_path: Path, run_id: str | None = None) -> RunManifest:
        git = GitAdapter(repo_path)
        store = RunStore(git.state_root())
        manifest = store.load_manifest(run_id) if run_id else store.find_latest_paused_run()
        if manifest is None:
            raise InconsistentStateError("No paused run found for this repository.")
        if manifest.status != "paused":
            raise InconsistentStateError(f"Run {manifest.run_id} is not paused.")

        items_payload = store.load_items(manifest.run_id)
        commit_plan = [CandidateCommit.from_dict(item) for item in items_payload.get("commits", [])]
        if manifest.current_commit_index >= len(commit_plan):
            raise InconsistentStateError("Paused run has no remaining commit to resume.")

        journal = store.journal(manifest.run_id)
        if not git.is_cherry_pick_in_progress():
            raise InconsistentStateError(
                "No cherry-pick in progress. Resolve the repository state or start a new run."
            )

        current_commit = commit_plan[manifest.current_commit_index]
        journal.record(
            "info",
            f"Continuing paused cherry-pick for {current_commit.commit_hash}.",
            phase="resume",
            item_key=",".join(current_commit.source_keys),
            commit_hash=current_commit.commit_hash,
            action="cherry-pick-continue",
            result="running",
        )
        outcome = git.cherry_pick_continue()
        if outcome.status == "conflict":
            items_payload = store.update_commit_status(manifest.run_id, current_commit.commit_hash, "conflict")
            store.write_resume_hints(
                manifest.run_id,
                self._resume_hint_text(manifest, current_commit.commit_hash),
            )
            raise ConflictPauseError(
                f"Conflict still unresolved for commit {current_commit.commit_hash}. Check resume-hints.txt."
            )

        manifest.applied_commit_count = max(manifest.applied_commit_count, manifest.current_commit_index + 1)
        manifest.current_commit_index += 1
        items_payload = store.update_commit_status(manifest.run_id, current_commit.commit_hash, "applied")
        manifest.status = "running"
        manifest.phase = "applying"
        manifest.paused_reason = None
        manifest.conflict_commit = None
        manifest.last_error = None
        store.write_manifest(manifest)
        journal.record(
            "info",
            f"Cherry-pick continued successfully for {current_commit.commit_hash}.",
            phase="resume",
            item_key=",".join(current_commit.source_keys),
            commit_hash=current_commit.commit_hash,
            action="cherry-pick-continue",
            result="ok",
        )
        return self._apply_commit_plan(store, journal, git, manifest, commit_plan, items_payload)

    def status(self, repo_path: Path, run_id: str | None = None) -> str:
        git = GitAdapter(repo_path)
        store = RunStore(git.state_root())
        manifest = store.load_manifest(run_id) if run_id else store.load_latest_manifest()
        if manifest is None:
            raise InconsistentStateError("No recorded runs found for this repository.")
        items_payload = store.load_items(manifest.run_id) if (store.run_dir(manifest.run_id) / "items.json").exists() else None
        lines = [
            f"Run ID: {manifest.run_id}",
            f"Status: {manifest.status}",
            f"Phase: {manifest.phase}",
            f"Branch: {manifest.branch_name}",
            f"Source Ref: {manifest.source_ref}",
            f"Target Ref: {manifest.target_ref}",
            f"Release IDs: {manifest.release_id or '-'}",
            f"Release Names: {manifest.release_name or '-'}",
            f"Stories: {', '.join(manifest.input_stories)}",
            f"Applied commits: {manifest.applied_commit_count}/{manifest.total_commits}",
            f"Conflicts: {manifest.conflict_count}",
        ]
        if manifest.paused_reason:
            lines.append(f"Paused reason: {manifest.paused_reason}")
        if manifest.conflict_commit:
            lines.append(f"Conflict commit: {manifest.conflict_commit}")
        if items_payload:
            stats = items_payload.get("stats", {})
            lines.append(f"Eligible items: {stats.get('eligible_item_count', 0)}")
            lines.append(f"Unmatched items: {stats.get('unmatched_item_count', 0)}")
        lines.append(f"Artifacts: {store.run_dir(manifest.run_id)}")
        return "\n".join(lines)

    def _create_manifest(
        self,
        git: GitAdapter,
        store: RunStore,
        story_keys: list[str],
        release_refs: list[ReleaseReference],
        *,
        release_id: str | None,
        release_name: str | None,
        fingerprint: str,
        source_ref: str,
        target_ref: str,
    ) -> RunManifest:
        run_started_at = datetime.now()
        generated_run_id = generate_run_id(git.repo_root.name, now=run_started_at)
        branch_release_name = (
            release_refs[0].release_name if len(release_refs) == 1 else release_name if not release_refs else None
        )
        branch_name = (
            build_release_branch_name(branch_release_name, now=run_started_at)
            if branch_release_name
            else f"equalizacao/{generated_run_id}"
        )
        manifest = RunManifest(
            run_id=branch_name,
            repo_path=str(git.repo_root),
            repo_slug=git.repo_root.name,
            branch_name=branch_name,
            input_stories=story_keys,
            release_id=release_id,
            release_name=release_name,
            fingerprint=fingerprint,
            status="initializing",
            phase="starting",
            current_commit_index=0,
            total_commits=0,
            applied_commit_count=0,
            conflict_count=0,
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
            source_ref=source_ref,
            target_ref=target_ref,
        )
        store.create_run(manifest)
        return manifest

    def _load_manifest_with_items(
        self,
        git: GitAdapter,
        run_id: str | None,
    ) -> tuple[RunManifest, RunStore, dict[str, Any]]:
        store = RunStore(git.state_root())
        manifest = store.load_manifest(run_id) if run_id else store.load_latest_manifest()
        if manifest is None:
            raise InconsistentStateError("No recorded runs found for this repository.")
        items_path = store.run_dir(manifest.run_id) / "items.json"
        if not items_path.exists():
            raise InconsistentStateError(f"Run {manifest.run_id} has no cached items. Execute fetch-jira first.")
        items_payload = store.load_items(manifest.run_id)
        return manifest, store, items_payload

    def _build_jira_snapshot(
        self,
        story_keys: list[str],
        journal: ExecutionJournal,
        *,
        story_release_map: dict[str, list[ReleaseReference]] | None = None,
    ) -> dict[str, Any]:
        normalized_story_release_map = story_release_map or {}
        story_results = self.jira.fetch_stories_with_subtasks(story_keys)

        story_items: list[JiraItem] = []
        story_payloads: list[dict[str, Any]] = []
        subtasks: list[JiraItem] = []
        for story_key, (story_item, story_subtasks) in zip(story_keys, story_results, strict=True):
            story_items.append(story_item)
            story_payloads.append(
                self._build_story_payload(story_item, normalized_story_release_map.get(story_item.key, []))
            )
            subtasks.extend(story_subtasks)
            journal.record(
                "info",
                f"Fetched Jira issue {story_key} with {len(story_subtasks)} subtasks.",
                phase="jira",
                item_key=story_key,
                action="jira-fetch",
                result="ok",
            )

        eligible_items = consolidate_items(story_keys, story_items, subtasks)
        return {
            "stories": story_payloads,
            "story_release_map": {
                key: [reference.to_dict() for reference in references]
                for key, references in normalized_story_release_map.items()
            },
            "eligible_items": [item.to_dict() for item in eligible_items],
            "matched_merges": [],
            "commits": [],
            "unmatched_item_keys": [],
            "stats": {
                "input_story_count": len(story_keys),
                "subtask_count": len(subtasks),
                "eligible_item_count": len(eligible_items),
                "matched_item_count": 0,
                "raw_commit_count": 0,
                "distinct_commit_count": 0,
                "unmatched_item_count": 0,
            },
        }

    def _build_commit_plan(
        self,
        items_payload: dict[str, Any],
        git: GitAdapter,
        journal: ExecutionJournal,
        *,
        source_ref: str,
    ) -> tuple[dict[str, Any], list[CandidateCommit]]:
        story_keys = [
            str(story.get("key", "")).strip()
            for story in items_payload.get("stories", [])
            if str(story.get("key", "")).strip()
        ]
        eligible_items = [JiraItem.from_dict(item) for item in items_payload.get("eligible_items", [])]
        if not story_keys or not eligible_items:
            raise InconsistentStateError("No cached Jira snapshot found for this run. Execute fetch-jira first.")

        eligible_item_keys = {item.key for item in eligible_items}
        merges = git.collect_merges(source_ref)

        raw_candidates: list[CandidateCommit] = []
        matched_item_keys: set[str] = set()
        matched_merges: list[str] = []
        for merge in merges:
            matched_keys = match_merge_to_items(merge.subject, eligible_item_keys)
            if not matched_keys:
                continue
            parents = git.get_merge_parents(merge.merge_hash)
            if parents is None:
                continue
            matched_item_keys.update(matched_keys)
            matched_merges.append(merge.merge_hash)
            raw_candidates.extend(
                git.list_branch_commits(
                    first_parent=parents[0],
                    branch_parent=parents[1],
                    source_merge=merge.merge_hash,
                    source_keys=matched_keys,
                )
            )

        distinct_commits = deduplicate_commits(raw_candidates)
        unmatched_item_keys = find_unmatched_item_keys(eligible_items, matched_item_keys)
        updated_payload = dict(items_payload)
        updated_payload["matched_merges"] = matched_merges
        updated_payload["commits"] = [{**commit.to_dict(), "cherry_pick_status": "pending"} for commit in distinct_commits]
        updated_payload["unmatched_item_keys"] = unmatched_item_keys
        stats = dict(items_payload.get("stats", {}))
        stats.update(
            {
                "input_story_count": len(story_keys),
                "eligible_item_count": len(eligible_items),
                "matched_item_count": len(matched_item_keys),
                "raw_commit_count": len(raw_candidates),
                "distinct_commit_count": len(distinct_commits),
                "unmatched_item_count": len(unmatched_item_keys),
            }
        )
        updated_payload["stats"] = stats
        return updated_payload, distinct_commits

    def _build_story_payload(
        self,
        story_item: JiraItem,
        release_refs: list[ReleaseReference],
    ) -> dict[str, Any]:
        payload = story_item.to_dict()
        payload["release_ids"] = [reference.release_id for reference in release_refs]
        payload["release_names"] = [reference.release_name for reference in release_refs]
        return payload

    def _mark_failed(
        self,
        store: RunStore,
        manifest: RunManifest,
        items_payload: dict[str, Any] | None,
        exc: Exception,
    ) -> None:
        if manifest.status == "paused":
            return
        manifest.status = "failed"
        manifest.phase = "failed"
        manifest.last_error = str(exc)
        store.write_manifest(manifest)
        store.write_summary(manifest.run_id, self._render_summary(manifest, items_payload))

    def _apply_commit_plan(
        self,
        store: RunStore,
        journal: ExecutionJournal,
        git: GitAdapter,
        manifest: RunManifest,
        commit_plan: list[CandidateCommit],
        items_payload: dict[str, Any],
    ) -> RunManifest:
        for index in range(manifest.current_commit_index, len(commit_plan)):
            commit = commit_plan[index]
            manifest.current_commit_index = index
            store.write_manifest(manifest)
            journal.record(
                "info",
                f"Applying commit {commit.commit_hash}: {commit.subject}",
                phase="applying",
                item_key=",".join(commit.source_keys),
                commit_hash=commit.commit_hash,
                action="cherry-pick",
                result="running",
            )
            outcome = git.cherry_pick(commit.commit_hash)
            if outcome.status == "conflict":
                items_payload = store.update_commit_status(manifest.run_id, commit.commit_hash, "conflict")
                manifest.status = "paused"
                manifest.phase = "paused"
                manifest.conflict_count += 1
                manifest.paused_reason = "Cherry-pick conflict"
                manifest.conflict_commit = commit.commit_hash
                manifest.last_error = outcome.stderr.strip() or "Cherry-pick conflict"
                store.write_manifest(manifest)
                store.write_resume_hints(
                    manifest.run_id,
                    self._resume_hint_text(manifest, commit.commit_hash),
                )
                store.write_summary(manifest.run_id, self._render_summary(manifest, items_payload))
                journal.record(
                    "warning",
                    f"Conflict while applying commit {commit.commit_hash}.",
                    phase="applying",
                    item_key=",".join(commit.source_keys),
                    commit_hash=commit.commit_hash,
                    action="cherry-pick",
                    result="conflict",
                )
                raise ConflictPauseError(
                    f"Conflict while applying commit {commit.commit_hash}. Check resume-hints.txt."
                )

            manifest.applied_commit_count = index + 1
            manifest.current_commit_index = index + 1
            items_payload = store.update_commit_status(manifest.run_id, commit.commit_hash, "applied")
            store.write_manifest(manifest)
            journal.record(
                "info",
                f"Commit {commit.commit_hash} applied.",
                phase="applying",
                item_key=",".join(commit.source_keys),
                commit_hash=commit.commit_hash,
                action="cherry-pick",
                result="ok",
            )

        manifest.status = "completed"
        manifest.phase = "completed"
        manifest.paused_reason = None
        manifest.conflict_commit = None
        manifest.last_error = None
        store.write_manifest(manifest)
        store.write_summary(manifest.run_id, self._render_summary(manifest, items_payload))
        journal.record("info", "Equalization run completed.", phase="completed", action="run-finish", result="ok")
        return manifest

    def _render_summary(self, manifest: RunManifest, items_payload: dict[str, Any] | None) -> str:
        stats = (items_payload or {}).get("stats", {})
        unmatched = (items_payload or {}).get("unmatched_item_keys", [])
        lines = [
            f"# Equalizador ProMax - Run {manifest.run_id}",
            "",
            f"- Status: {manifest.status}",
            f"- Branch: {manifest.branch_name}",
            f"- Origem: {manifest.source_ref}",
            f"- Destino: {manifest.target_ref}",
            f"- Release IDs: {manifest.release_id or '-'}",
            f"- Release Names: {manifest.release_name or '-'}",
            f"- Stories de entrada: {stats.get('input_story_count', len(manifest.input_stories))}",
            f"- Subtasks obtidas: {stats.get('subtask_count', 0)}",
            f"- Itens elegiveis: {stats.get('eligible_item_count', 0)}",
            f"- Commits encontrados (bruto): {stats.get('raw_commit_count', 0)}",
            f"- Commits distintos: {stats.get('distinct_commit_count', manifest.total_commits)}",
            f"- Commits aplicados: {manifest.applied_commit_count}",
            f"- Conflitos: {manifest.conflict_count}",
            f"- Itens sem correspondencia: {stats.get('unmatched_item_count', 0)}",
        ]
        if manifest.conflict_commit:
            lines.append(f"- Commit em conflito: {manifest.conflict_commit}")
        if unmatched:
            lines.extend(["", "## Itens sem correspondencia", *[f"- {item_key}" for item_key in unmatched]])
        return "\n".join(lines) + "\n"

    def _resume_hint_text(self, manifest: RunManifest, commit_hash: str) -> str:
        return (
            f"Run: {manifest.run_id}\n"
            f"Branch: {manifest.branch_name}\n"
            f"Origem: {manifest.source_ref}\n"
            f"Destino: {manifest.target_ref}\n"
            f"Commit em conflito: {commit_hash}\n\n"
            "Passos sugeridos:\n"
            "1. Resolva os arquivos conflitados.\n"
            "2. Deixe o cherry-pick pronto para continuacao.\n"
            "3. Execute: python -m equalizador_promax resume --repo <caminho-do-repo> --run-id "
            f"{manifest.run_id}\n"
        )
