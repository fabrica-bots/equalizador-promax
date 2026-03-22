from __future__ import annotations

from pathlib import Path
from datetime import datetime

from equalizador_promax.config import AppConfig, load_config
from equalizador_promax.correlation import (
    consolidate_items,
    deduplicate_commits,
    find_unmatched_item_keys,
    match_merge_to_item,
    normalize_story_keys,
)
from equalizador_promax.errors import ConflictPauseError, InconsistentStateError, ValidationError
from equalizador_promax.git_adapter import GitAdapter
from equalizador_promax.jira_client import JiraClient
from equalizador_promax.models import CandidateCommit, DoctorCheck, JiraItem, RunManifest
from equalizador_promax.run_store import ExecutionJournal, RunStore
from equalizador_promax.utils import build_release_branch_name, calculate_fingerprint, generate_run_id, utc_now_iso


class EqualizadorService:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or load_config()
        self.jira = JiraClient(self.config.jira)

    def doctor(self, repo_path: Path) -> list[DoctorCheck]:
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

        for ref_name in ("develop", "origin/quality"):
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
        *,
        force_new: bool = False,
        release_id: str | None = None,
        release_name: str | None = None,
    ) -> RunManifest:
        normalized_stories = normalize_story_keys(story_keys)
        if not normalized_stories:
            raise ValidationError("At least one story key must be informed.")

        git = GitAdapter(repo_path)
        git.fetch_origin()
        git.ensure_ref_exists("develop")
        git.ensure_ref_exists("origin/quality")
        git.ensure_clean_working_tree()

        store = RunStore(git.state_root())
        store.ensure_writable()
        fingerprint = calculate_fingerprint(git.repo_root, normalized_stories)
        existing = store.find_open_run(fingerprint)
        if existing and not force_new:
            raise InconsistentStateError(
                f"Existing unfinished run detected ({existing.run_id}). Use resume or --force-new."
            )

        run_started_at = datetime.now()
        generated_run_id = generate_run_id(git.repo_root.name, now=run_started_at)
        branch_name = (
            build_release_branch_name(release_name, now=run_started_at)
            if release_name
            else f"equalizacao/{generated_run_id}"
        )
        run_id = branch_name
        manifest = RunManifest(
            run_id=run_id,
            repo_path=str(git.repo_root),
            repo_slug=git.repo_root.name,
            branch_name=branch_name,
            input_stories=normalized_stories,
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
        )
        store.create_run(manifest)
        journal = store.journal(run_id)
        journal.record("info", "Starting equalization run.", phase="starting", action="run-start", result="ok")

        items_payload: dict[str, object] | None = None
        try:
            items_payload, commit_plan = self._build_execution_plan(normalized_stories, git, journal)
            manifest.total_commits = len(commit_plan)
            store.write_items(run_id, items_payload)
            journal.record(
                "info",
                f"Execution plan assembled with {len(commit_plan)} distinct commits.",
                phase="planning",
                action="plan",
                result="ok",
            )

            git.create_equalization_branch(manifest.branch_name)
            journal.record(
                "info",
                f"Created branch {manifest.branch_name} from origin/quality.",
                phase="branching",
                action="branch-create",
                result="ok",
            )
            manifest.status = "running"
            manifest.phase = "applying"
            store.write_manifest(manifest)
            return self._apply_commit_plan(store, journal, git, manifest, commit_plan, items_payload)
        except Exception as exc:
            if manifest.status != "paused":
                manifest.status = "failed"
                manifest.phase = "failed"
                manifest.last_error = str(exc)
                store.write_manifest(manifest)
                store.write_summary(manifest.run_id, self._render_summary(manifest, items_payload))
            raise

    def resolve_story_keys(self, story_keys: list[str] | None = None) -> list[str]:
        normalized = normalize_story_keys(story_keys or [])
        if not normalized:
            raise ValidationError("At least one story key must be informed.")
        return normalized

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
            f"Release ID: {manifest.release_id or '-'}",
            f"Release Name: {manifest.release_name or '-'}",
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

    def _build_execution_plan(
        self,
        story_keys: list[str],
        git: GitAdapter,
        journal: ExecutionJournal,
    ) -> tuple[dict[str, object], list[CandidateCommit]]:
        story_items: list[JiraItem] = []
        subtasks: list[JiraItem] = []
        for story_key in story_keys:
            story_item, story_subtasks = self.jira.fetch_story_with_subtasks(story_key)
            story_items.append(story_item)
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
        eligible_item_keys = {item.key for item in eligible_items}
        merges = git.collect_merges("develop")

        raw_candidates: list[CandidateCommit] = []
        matched_item_keys: set[str] = set()
        matched_merges: list[str] = []
        for merge in merges:
            matched_key = match_merge_to_item(merge.subject, eligible_item_keys)
            if not matched_key:
                continue
            parents = git.get_merge_parents(merge.merge_hash)
            if parents is None:
                continue
            matched_item_keys.add(matched_key)
            matched_merges.append(merge.merge_hash)
            raw_candidates.extend(
                git.list_branch_commits(
                    first_parent=parents[0],
                    branch_parent=parents[1],
                    source_merge=merge.merge_hash,
                    source_key=matched_key,
                )
            )

        distinct_commits = deduplicate_commits(raw_candidates)
        unmatched_item_keys = find_unmatched_item_keys(eligible_items, matched_item_keys)

        payload = {
            "stories": [item.to_dict() for item in story_items],
            "eligible_items": [item.to_dict() for item in eligible_items],
            "matched_merges": matched_merges,
            "commits": [{**commit.to_dict(), "cherry_pick_status": "pending"} for commit in distinct_commits],
            "unmatched_item_keys": unmatched_item_keys,
            "stats": {
                "input_story_count": len(story_keys),
                "subtask_count": len(subtasks),
                "eligible_item_count": len(eligible_items),
                "matched_item_count": len(matched_item_keys),
                "raw_commit_count": len(raw_candidates),
                "distinct_commit_count": len(distinct_commits),
                "unmatched_item_count": len(unmatched_item_keys),
            },
        }
        return payload, distinct_commits

    def _apply_commit_plan(
        self,
        store: RunStore,
        journal: ExecutionJournal,
        git: GitAdapter,
        manifest: RunManifest,
        commit_plan: list[CandidateCommit],
        items_payload: dict[str, object],
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

    def _render_summary(self, manifest: RunManifest, items_payload: dict[str, object] | None) -> str:
        stats = (items_payload or {}).get("stats", {})
        unmatched = (items_payload or {}).get("unmatched_item_keys", [])
        lines = [
            f"# Equalizador ProMax - Run {manifest.run_id}",
            "",
            f"- Status: {manifest.status}",
            f"- Branch: {manifest.branch_name}",
            f"- Release ID: {manifest.release_id or '-'}",
            f"- Release Name: {manifest.release_name or '-'}",
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
            f"Commit em conflito: {commit_hash}\n\n"
            "Passos sugeridos:\n"
            "1. Resolva os arquivos conflitados.\n"
            "2. Deixe o cherry-pick pronto para continuacao.\n"
            "3. Execute: python -m equalizador_promax resume --repo <caminho-do-repo> --run-id "
            f"{manifest.run_id}\n"
        )
