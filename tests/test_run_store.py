import csv
import tempfile
import unittest
from pathlib import Path

from equalizador_promax.models import RunManifest
from equalizador_promax.run_store import RunStore


class RunStoreTests(unittest.TestCase):
    def test_write_items_creates_requested_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RunStore(Path(temp_dir))
            run_id = "20260321-210345-repo"
            store.run_dir(run_id).mkdir(parents=True, exist_ok=True)
            payload = {
                "stories": [
                    {"key": "SQCRM-7637", "release_ids": ["59571"], "release_names": ["Versão Release 58"]},
                    {
                        "key": "SQCRM-7638",
                        "release_ids": ["59571", "59572"],
                        "release_names": ["Versão Release 58", "Versão Release 59"],
                    },
                    {"key": "SQCRM-7639", "release_ids": [], "release_names": []},
                ],
                "eligible_items": [
                    {"key": "SQCRM-7637", "item_type": "story", "parent_key": None},
                    {"key": "SQCRM-7693", "item_type": "subtask", "parent_key": "SQCRM-7637"},
                    {"key": "SQCRM-7638", "item_type": "story", "parent_key": None},
                    {"key": "SQCRM-7700", "item_type": "subtask", "parent_key": "SQCRM-7638"},
                    {"key": "SQCRM-7639", "item_type": "story", "parent_key": None},
                ],
                "commits": [
                    {
                        "commit_hash": "abc123",
                        "timestamp": 1711051425,
                        "author": "Lucas",
                        "subject": "feat: ajuste",
                        "source_keys": ["SQCRM-7637"],
                        "cherry_pick_status": "conflict",
                    }
                ],
            }

            store.write_items(run_id, payload)

            stories_txt = (store.run_dir(run_id) / "stories.txt").read_text(encoding="utf-8")
            subtasks_txt = (store.run_dir(run_id) / "subtasks_por_story.txt").read_text(encoding="utf-8")
            with (store.run_dir(run_id) / "commits.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(
                stories_txt,
                "SQCRM-7637 [Release: Versão Release 58]\n"
                "SQCRM-7638 [Releases: Versão Release 58, Versão Release 59]\n"
                "SQCRM-7639\n",
            )
            self.assertIn("SQCRM-7637 [Release: Versão Release 58]\n- SQCRM-7693", subtasks_txt)
            self.assertIn(
                "SQCRM-7638 [Releases: Versão Release 58, Versão Release 59]\n- SQCRM-7700",
                subtasks_txt,
            )
            self.assertIn("SQCRM-7639\n- <sem subtasks>", subtasks_txt)
            self.assertEqual(rows[0]["commit_hash"], "abc123")
            self.assertEqual(rows[0]["author"], "Lucas")
            self.assertEqual(rows[0]["cherry_pick_status"], "conflict")

    def test_list_manifests_supports_nested_run_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = RunStore(Path(temp_dir))
            manifest = RunManifest(
                run_id="equalizacao/versao_release_58_21-03-2026-21-20-50",
                repo_path="C:/repo",
                repo_slug="repo",
                branch_name="equalizacao/versao_release_58_21-03-2026-21-20-50",
                input_stories=["SQCRM-7637"],
                release_id="59571",
                release_name="Versão Release 58",
                fingerprint="abc",
                status="paused",
                phase="paused",
                current_commit_index=0,
                total_commits=1,
                applied_commit_count=0,
                conflict_count=1,
                created_at="2026-03-21T21:20:50+00:00",
                updated_at="2026-03-21T21:20:50+00:00",
            )

            store.create_run(manifest)
            loaded = store.list_manifests()

            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].run_id, manifest.run_id)


if __name__ == "__main__":
    unittest.main()
