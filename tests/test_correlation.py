import unittest

from equalizador_promax.correlation import (
    consolidate_items,
    deduplicate_commits,
    find_unmatched_item_keys,
    match_merge_to_items,
    normalize_release_ids,
    normalize_story_keys,
)
from equalizador_promax.models import CandidateCommit, JiraItem


class CorrelationTests(unittest.TestCase):
    def test_normalize_story_keys_deduplicates_and_uppercases(self) -> None:
        self.assertEqual(
            normalize_story_keys(["sqcrm-1", " SQCRM-1 ", "", "sqcrm-2"]),
            ["SQCRM-1", "SQCRM-2"],
        )

    def test_normalize_release_ids_deduplicates(self) -> None:
        self.assertEqual(
            normalize_release_ids(["59571", " 59571 ", "", "59572"]),
            ["59571", "59572"],
        )

    def test_match_merge_returns_all_eligible_keys(self) -> None:
        eligible = {"SQCRM-1", "SQCRM-2"}
        self.assertEqual(match_merge_to_items("Merge PR 100 - SQCRM-1 ajuste", eligible), ("SQCRM-1",))
        self.assertEqual(
            match_merge_to_items("Merge PR 101 - GitHub-EDP/SQCRM-1_SQCRM-2_bug", eligible),
            ("SQCRM-1", "SQCRM-2"),
        )
        self.assertEqual(match_merge_to_items("Merge PR 102 - sem issue", eligible), ())

    def test_consolidate_and_find_unmatched_items(self) -> None:
        story_items = [JiraItem(key="SQCRM-1", parent_key=None, item_type="story")]
        subtasks = [
            JiraItem(key="SQCRM-3", parent_key="SQCRM-1", item_type="subtask"),
            JiraItem(key="SQCRM-4", parent_key="SQCRM-1", item_type="subtask"),
        ]
        consolidated = consolidate_items(["SQCRM-1"], story_items, subtasks)
        self.assertEqual([item.key for item in consolidated], ["SQCRM-1", "SQCRM-3", "SQCRM-4"])
        self.assertEqual(find_unmatched_item_keys(consolidated, {"SQCRM-1"}), ["SQCRM-3", "SQCRM-4"])

    def test_deduplicate_commits_keeps_single_hash_and_merges_sources(self) -> None:
        commits = [
            CandidateCommit(
                commit_hash="abc123",
                timestamp=10,
                author="Ana",
                subject="feat: ajuste",
                source_merge="merge-a",
                source_keys=("SQCRM-1",),
            ),
            CandidateCommit(
                commit_hash="abc123",
                timestamp=11,
                author="Ana",
                subject="feat: ajuste",
                source_merge="merge-b",
                source_keys=("SQCRM-2",),
            ),
        ]
        deduped = deduplicate_commits(commits)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0].source_keys, ("SQCRM-1", "SQCRM-2"))


if __name__ == "__main__":
    unittest.main()
