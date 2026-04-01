import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from equalizador_promax.gui import (
    global_secret_path,
    global_state_dir,
    latest_commits_csv_path,
    latest_run_directory,
    load_commit_grid_rows,
)


class GuiPathTests(unittest.TestCase):
    @patch("equalizador_promax.gui.default_config_path")
    def test_gui_paths_are_stored_under_global_app_directory(self, mocked_default_config_path) -> None:
        mocked_default_config_path.return_value = Path(r"C:\Users\lucas\AppData\Roaming\EqualizadorProMax\config.toml")

        self.assertEqual(global_state_dir(), Path(r"C:\Users\lucas\AppData\Roaming\EqualizadorProMax"))
        self.assertEqual(global_secret_path(), Path(r"C:\Users\lucas\AppData\Roaming\EqualizadorProMax\gui-secret.txt"))

    def test_latest_run_directory_and_commits_csv_path_follow_latest_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            first_run = repo_root / ".git" / "equalizador-promax" / "runs" / "run-a"
            second_run = repo_root / ".git" / "equalizador-promax" / "runs" / "run-b"
            first_run.mkdir(parents=True, exist_ok=True)
            second_run.mkdir(parents=True, exist_ok=True)
            (first_run / "manifest.json").write_text("{}", encoding="utf-8")
            (first_run / "commits.csv").write_text("commit_hash\nabc\n", encoding="utf-8")
            (second_run / "manifest.json").write_text("{}", encoding="utf-8")
            (second_run / "commits.csv").write_text("commit_hash\ndef\n", encoding="utf-8")

            os.utime(first_run / "manifest.json", (1, 1))
            os.utime(second_run / "manifest.json", (2, 2))

            self.assertEqual(latest_run_directory(repo_root), second_run)
            self.assertEqual(latest_commits_csv_path(repo_root), second_run / "commits.csv")

    def test_load_commit_grid_rows_reads_expected_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            commits_csv_path = Path(temp_dir) / "commits.csv"
            commits_csv_path.write_text(
                "commit_hash,commit_datetime_utc,author,subject,source_keys,cherry_pick_status\n"
                "abc123,2026-04-01T12:00:00+00:00,Lucas,feat: ajuste,SQCRM-1,applied\n",
                encoding="utf-8",
            )

            rows = load_commit_grid_rows(commits_csv_path)

            self.assertEqual(
                rows,
                [("applied", "abc123", "2026-04-01T12:00:00+00:00", "Lucas")],
            )


if __name__ == "__main__":
    unittest.main()
