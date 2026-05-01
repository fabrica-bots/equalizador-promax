import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from equalizador_promax.config import AppConfig, JiraSettings
from equalizador_promax.errors import ValidationError
from equalizador_promax.git_adapter import CherryPickOutcome
from equalizador_promax.models import CandidateCommit, JiraItem, JiraPullRequest, MergeRecord, ReleaseReference
from equalizador_promax.orchestrator import EqualizadorService
from equalizador_promax.run_store import RunStore


class OrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        config = AppConfig(jira=JiraSettings(base_url="https://jira.example", auth_mode="token"), config_path=None)
        self.service = EqualizadorService(config)
        self.service.jira = Mock()

    def test_resolve_story_keys_from_manual_input(self) -> None:
        self.assertEqual(
            self.service.resolve_story_keys(story_keys=["sqcrm-1", "SQCRM-1", "sqcrm-2"]),
            ["SQCRM-1", "SQCRM-2"],
        )

    def test_resolve_release(self) -> None:
        self.service.jira.fetch_release_name.return_value = "Versão Release 58"
        self.service.jira.fetch_release_issue_keys.return_value = ["sqcrm-10", "SQCRM-11"]
        issue_keys, release_name = self.service.resolve_release("59571")

        self.assertEqual(issue_keys, ["SQCRM-10", "SQCRM-11"])
        self.assertEqual(release_name, "Versão Release 58")
        self.service.jira.fetch_release_name.assert_called_once_with("59571")
        self.service.jira.fetch_release_issue_keys.assert_called_once_with("59571")

    def test_resolve_inputs_combines_release_and_manual_stories(self) -> None:
        self.service.jira.fetch_release_name.side_effect = ["Release 58", "Release 59"]
        self.service.jira.fetch_release_issue_keys.side_effect = [
            ["sqcrm-10", "SQCRM-11"],
            ["SQCRM-11", "sqcrm-12"],
        ]

        story_keys, release_refs, story_release_map = self.service.resolve_inputs(
            release_ids=["59571", "59572"],
            story_keys=["sqcrm-12", "sqcrm-13", "SQCRM-10"],
        )

        self.assertEqual(story_keys, ["SQCRM-10", "SQCRM-11", "SQCRM-12", "SQCRM-13"])
        self.assertEqual([reference.release_id for reference in release_refs], ["59571", "59572"])
        self.assertEqual([reference.release_name for reference in release_refs], ["Release 58", "Release 59"])
        self.assertEqual(
            [reference.release_id for reference in story_release_map["SQCRM-11"]],
            ["59571", "59572"],
        )
        self.assertEqual(
            [reference.release_name for reference in story_release_map["SQCRM-12"]],
            ["Release 59"],
        )

    def test_resolve_story_keys_rejects_empty_release_result(self) -> None:
        self.service.jira.fetch_release_name.return_value = "Versão Release 58"
        self.service.jira.fetch_release_issue_keys.return_value = []
        with self.assertRaises(ValidationError):
            self.service.resolve_release("59571")

    def test_resolve_inputs_rejects_empty_manual_and_release_values(self) -> None:
        with self.assertRaises(ValidationError):
            self.service.resolve_inputs([], [])

    def test_build_jira_snapshot_keeps_release_metadata(self) -> None:
        self.service.jira.fetch_stories_with_subtasks.return_value = [
            (
                JiraItem(key="CRMBR-3760", parent_key=None, item_type="story"),
                [JiraItem(key="CRMBR-3808", parent_key="CRMBR-3760", item_type="subtask")],
            ),
            (
                JiraItem(key="CRMBR-3761", parent_key=None, item_type="story"),
                [JiraItem(key="CRMBR-3810", parent_key="CRMBR-3761", item_type="subtask")],
            ),
        ]
        journal = Mock()

        payload = self.service._build_jira_snapshot(
            ["CRMBR-3760", "CRMBR-3761"],
            journal,
            story_release_map={
                "CRMBR-3760": [ReleaseReference(release_id="59571", release_name="Release 58")]
            },
        )

        self.assertEqual(payload["stats"]["eligible_item_count"], 4)
        self.assertEqual(payload["stats"]["subtask_count"], 2)
        self.assertEqual(payload["stories"][0]["release_ids"], ["59571"])
        self.assertEqual(payload["stories"][0]["release_names"], ["Release 58"])
        self.assertEqual(payload["commits"], [])
        self.service.jira.fetch_stories_with_subtasks.assert_called_once_with(["CRMBR-3760", "CRMBR-3761"])

    def test_build_commit_plan_matches_multi_issue_merge_and_keeps_distinct_commit_list(self) -> None:
        payload = {
            "stories": [
                {"key": "CRMBR-3760", "release_ids": [], "release_names": []},
                {"key": "CRMBR-3761", "release_ids": [], "release_names": []},
            ],
            "eligible_items": [
                {"key": "CRMBR-3760", "parent_key": None, "item_type": "story"},
                {"key": "CRMBR-3808", "parent_key": "CRMBR-3760", "item_type": "subtask"},
                {"key": "CRMBR-3761", "parent_key": None, "item_type": "story"},
                {"key": "CRMBR-3810", "parent_key": "CRMBR-3761", "item_type": "subtask"},
            ],
            "stats": {"subtask_count": 2},
        }

        git = Mock()
        git.repo_root = Path(r"C:\repo\msdyn-crm-b2b-webresources")
        git.collect_merges.return_value = [
            MergeRecord(
                merge_hash="merge-a",
                timestamp=10,
                subject="Merge pull request #506 from GitHub-EDP/CRMBR-3760_CRMBR-3808_e_CRMBR-3761_CRMBR-3810_bug",
            ),
            MergeRecord(
                merge_hash="merge-b",
                timestamp=11,
                subject="Merge pull request #503 from GitHub-EDP/CRMBR-3760_CRMBR-3808_e_CRMBR-3761_CRMBR-3810_bug",
            ),
        ]
        git.get_merge_parents.side_effect = [("base-a", "branch-a"), ("base-b", "branch-b")]
        git.list_branch_commits.side_effect = [
            [
                CandidateCommit(
                    commit_hash="abc123",
                    timestamp=10,
                    author="Ana",
                    subject="CRMBR-3760_CRMBR-3808_e_CRMBR-3761_CRMBR-3810",
                    source_merge="merge-a",
                    source_keys=("CRMBR-3760", "CRMBR-3761", "CRMBR-3808", "CRMBR-3810"),
                )
            ],
            [
                CandidateCommit(
                    commit_hash="abc123",
                    timestamp=11,
                    author="Ana",
                    subject="CRMBR-3760_CRMBR-3808_e_CRMBR-3761_CRMBR-3810",
                    source_merge="merge-b",
                    source_keys=("CRMBR-3760", "CRMBR-3761", "CRMBR-3808", "CRMBR-3810"),
                )
            ],
        ]
        self.service.jira.fetch_pull_requests_for_issue_keys.return_value = {}
        journal = Mock()

        updated_payload, commits = self.service._build_commit_plan(
            payload,
            git,
            journal,
            source_ref="origin/develop",
            target_ref="origin/quality",
        )

        self.assertEqual(updated_payload["matched_merges"], ["merge-a", "merge-b"])
        self.assertEqual(updated_payload["stats"]["matched_item_count"], 4)
        self.assertEqual(updated_payload["stats"]["raw_commit_count"], 2)
        self.assertEqual(updated_payload["stats"]["distinct_commit_count"], 1)
        self.assertEqual(updated_payload["unmatched_item_keys"], [])
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0].source_keys, ("CRMBR-3760", "CRMBR-3761", "CRMBR-3808", "CRMBR-3810"))
        git.list_branch_commits.assert_any_call(
            first_parent="base-a",
            branch_parent="branch-a",
            source_merge="merge-a",
            source_keys=("CRMBR-3760", "CRMBR-3761", "CRMBR-3808", "CRMBR-3810"),
        )

    def test_build_commit_plan_marks_commit_already_transferred_to_target_from_jira_pr(self) -> None:
        payload = {
            "stories": [{"key": "SQCRM-7691", "release_ids": [], "release_names": []}],
            "eligible_items": [
                {"key": "SQCRM-7691", "parent_key": None, "item_type": "story", "issue_id": "10001"},
            ],
            "stats": {},
        }

        git = Mock()
        git.repo_root = Path(r"C:\repo\msdyn-crm-b2b-webresources")
        git.collect_merges.return_value = [
            MergeRecord(
                merge_hash="merge-a",
                timestamp=10,
                subject="Merge pull request #58 from GitHub-EDP/SQCRM-7691_feature",
            )
        ]
        git.get_merge_parents.return_value = ("base-a", "branch-a")
        git.list_branch_commits.return_value = [
            CandidateCommit(
                commit_hash="abc123",
                timestamp=10,
                author="Ana",
                subject="SQCRM-7691 ajuste",
                source_merge="merge-a",
                source_keys=("SQCRM-7691",),
            )
        ]
        self.service.jira.fetch_pull_requests_for_issue_keys.return_value = {
            "SQCRM-7691": [
                JiraPullRequest(
                    issue_key="SQCRM-7691",
                    issue_id="10001",
                    pr_id="58",
                    title="Release 58",
                    url="https://git.example/pr/58",
                    status="MERGED",
                    source_branch="equalizacao/bravo_release_58_00",
                    destination_branch="quality",
                    repository_name="msdyn-crm-b2b-webresources",
                )
            ]
        }
        journal = Mock()

        updated_payload, _commits = self.service._build_commit_plan(
            payload,
            git,
            journal,
            source_ref="origin/develop",
            target_ref="origin/quality",
        )

        self.assertEqual(updated_payload["commits"][0]["ja_no_destino"], "sim")
        self.assertIn("https://git.example/pr/58", updated_payload["commits"][0]["prs_destino"])
        self.assertEqual(updated_payload["stats"]["target_transferred_commit_count"], 1)

    def test_apply_cherry_picks_skips_commit_when_cherry_pick_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_root = Path(temp_dir)
            store = RunStore(state_root)
            manifest = self.service._create_manifest(
                Mock(repo_root=Path(r"C:\repo")),
                store,
                ["SQCRM-1"],
                [],
                release_id=None,
                release_name=None,
                fingerprint="fp-1",
                source_ref="origin/develop",
                target_ref="origin/quality",
            )
            manifest.status = "commits-ready"
            manifest.phase = "commits-ready"
            manifest.total_commits = 2
            store.write_manifest(manifest)
            store.write_items(
                manifest.run_id,
                {
                    "stories": [{"key": "SQCRM-1", "release_ids": [], "release_names": []}],
                    "eligible_items": [{"key": "SQCRM-1", "parent_key": None, "item_type": "story"}],
                    "commits": [
                        {
                            "commit_hash": "abc123",
                            "timestamp": 10,
                            "author": "Ana",
                            "subject": "feat: primeiro",
                            "source_merge": "merge-a",
                            "source_keys": ["SQCRM-1"],
                            "cherry_pick_status": "pending",
                        },
                        {
                            "commit_hash": "def456",
                            "timestamp": 11,
                            "author": "Ana",
                            "subject": "feat: segundo",
                            "source_merge": "merge-b",
                            "source_keys": ["SQCRM-1"],
                            "cherry_pick_status": "pending",
                        },
                    ],
                    "stats": {"distinct_commit_count": 2},
                },
            )

            git = Mock()
            git.state_root.return_value = state_root
            git.is_cherry_pick_in_progress.return_value = False
            git.cherry_pick.side_effect = [
                CherryPickOutcome(status="empty", stdout="", stderr=""),
                CherryPickOutcome(status="applied", stdout="", stderr=""),
            ]

            with patch("equalizador_promax.orchestrator.GitAdapter", return_value=git):
                updated_manifest = self.service.apply_cherry_picks(Path(r"C:\repo"), manifest.run_id)

            items_payload = store.load_items(manifest.run_id)
            self.assertEqual(updated_manifest.status, "completed")
            self.assertEqual(updated_manifest.current_commit_index, 2)
            self.assertEqual(updated_manifest.applied_commit_count, 1)
            self.assertEqual(items_payload["commits"][0]["cherry_pick_status"], "skipped-empty")
            self.assertEqual(items_payload["commits"][1]["cherry_pick_status"], "applied")
            git.cherry_pick_skip.assert_called_once_with()

    def test_resume_skips_empty_cherry_pick_and_continues_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_root = Path(temp_dir)
            store = RunStore(state_root)
            manifest = self.service._create_manifest(
                Mock(repo_root=Path(r"C:\repo")),
                store,
                ["SQCRM-1"],
                [],
                release_id=None,
                release_name=None,
                fingerprint="fp-2",
                source_ref="origin/develop",
                target_ref="origin/quality",
            )
            manifest.status = "paused"
            manifest.phase = "paused"
            manifest.total_commits = 2
            manifest.current_commit_index = 0
            manifest.conflict_count = 1
            manifest.conflict_commit = "abc123"
            store.write_manifest(manifest)
            store.write_items(
                manifest.run_id,
                {
                    "stories": [{"key": "SQCRM-1", "release_ids": [], "release_names": []}],
                    "eligible_items": [{"key": "SQCRM-1", "parent_key": None, "item_type": "story"}],
                    "commits": [
                        {
                            "commit_hash": "abc123",
                            "timestamp": 10,
                            "author": "Ana",
                            "subject": "feat: primeiro",
                            "source_merge": "merge-a",
                            "source_keys": ["SQCRM-1"],
                            "cherry_pick_status": "conflict",
                        },
                        {
                            "commit_hash": "def456",
                            "timestamp": 11,
                            "author": "Ana",
                            "subject": "feat: segundo",
                            "source_merge": "merge-b",
                            "source_keys": ["SQCRM-1"],
                            "cherry_pick_status": "pending",
                        },
                    ],
                    "stats": {"distinct_commit_count": 2},
                },
            )

            git = Mock()
            git.state_root.return_value = state_root
            git.is_cherry_pick_in_progress.return_value = True
            git.cherry_pick_continue.return_value = CherryPickOutcome(status="empty", stdout="", stderr="")
            git.cherry_pick.return_value = CherryPickOutcome(status="applied", stdout="", stderr="")

            with patch("equalizador_promax.orchestrator.GitAdapter", return_value=git):
                updated_manifest = self.service.resume(Path(r"C:\repo"), manifest.run_id)

            items_payload = store.load_items(manifest.run_id)
            self.assertEqual(updated_manifest.status, "completed")
            self.assertEqual(updated_manifest.current_commit_index, 2)
            self.assertEqual(updated_manifest.applied_commit_count, 1)
            self.assertIsNone(updated_manifest.conflict_commit)
            self.assertEqual(items_payload["commits"][0]["cherry_pick_status"], "skipped-empty")
            self.assertEqual(items_payload["commits"][1]["cherry_pick_status"], "applied")
            git.cherry_pick_skip.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
