import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from equalizador_promax.errors import GitCommandError
from equalizador_promax.git_adapter import GitAdapter


class GitAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = object.__new__(GitAdapter)
        self.adapter.repo_path = Path(r"C:\repo")
        self.adapter.repo_root = Path(r"C:\repo")

    def test_classify_cherry_pick_outcome_marks_empty_when_no_changes_remain(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["git", "cherry-pick", "--continue"],
            returncode=1,
            stdout="",
            stderr="",
        )

        with (
            patch.object(self.adapter, "is_cherry_pick_in_progress", return_value=True),
            patch.object(self.adapter, "has_unmerged_paths", return_value=False),
            patch.object(self.adapter, "status_porcelain", return_value=""),
        ):
            outcome = self.adapter._classify_cherry_pick_outcome(completed)

        self.assertEqual(outcome.status, "empty")

    def test_classify_cherry_pick_outcome_keeps_conflict_when_unmerged_paths_exist(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["git", "cherry-pick", "--continue"],
            returncode=1,
            stdout="",
            stderr="",
        )

        with (
            patch.object(self.adapter, "is_cherry_pick_in_progress", return_value=True),
            patch.object(self.adapter, "has_unmerged_paths", return_value=True),
        ):
            outcome = self.adapter._classify_cherry_pick_outcome(completed)

        self.assertEqual(outcome.status, "conflict")

    def test_classify_cherry_pick_outcome_raises_when_git_is_not_in_cherry_pick_state(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["git", "cherry-pick", "--continue"],
            returncode=1,
            stdout="",
            stderr="fatal",
        )

        with patch.object(self.adapter, "is_cherry_pick_in_progress", return_value=False):
            with self.assertRaises(GitCommandError):
                self.adapter._classify_cherry_pick_outcome(completed)


if __name__ == "__main__":
    unittest.main()
