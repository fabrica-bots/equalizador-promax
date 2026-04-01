import unittest
from unittest.mock import Mock

from equalizador_promax.config import JiraSettings
from equalizador_promax.jira_client import JiraClient


class JiraClientTests(unittest.TestCase):
    def test_fetch_release_name(self) -> None:
        client = JiraClient(JiraSettings(base_url="https://jira.example", auth_mode="token"))
        raw_client = Mock()
        raw_client._get_json.return_value = {"name": "Versão Release 58"}
        client._client = raw_client

        result = client.fetch_release_name("59571")

        self.assertEqual(result, "Versão Release 58")
        raw_client._get_json.assert_called_once_with("version/59571")

    def test_fetch_release_issue_keys_uses_raw_search_and_filters_subtasks(self) -> None:
        client = JiraClient(JiraSettings(base_url="https://jira.example", auth_mode="token"))
        raw_client = Mock()
        raw_client._get_json.side_effect = [
            {
                "issues": [
                    {"key": "SQCRM-7637", "fields": {}},
                    {"key": "SQCRM-9999", "fields": {"parent": {"key": "SQCRM-7637"}}},
                    {"key": "SQCRM-7638", "fields": {}},
                ],
                "total": 2,
            }
        ]
        client._client = raw_client

        result = client.fetch_release_issue_keys("59571")

        self.assertEqual(result, ["SQCRM-7637", "SQCRM-7638"])
        raw_client._get_json.assert_called_once()

    def test_fetch_stories_with_subtasks_uses_batched_search_and_preserves_requested_order(self) -> None:
        client = JiraClient(JiraSettings(base_url="https://jira.example", auth_mode="token"))
        client.story_batch_size = 2
        raw_client = Mock()
        raw_client._get_json.side_effect = [
            {
                "issues": [
                    {
                        "key": "SQCRM-7637",
                        "fields": {
                            "issuetype": {"name": "story"},
                            "subtasks": [{"key": "SQCRM-8001"}],
                        },
                    },
                    {
                        "key": "SQCRM-7638",
                        "fields": {
                            "issuetype": {"name": "story"},
                            "subtasks": [],
                        },
                    },
                ]
            },
            {
                "issues": [
                    {
                        "key": "SQCRM-7639",
                        "fields": {
                            "issuetype": {"name": "story"},
                            "subtasks": [{"key": "SQCRM-8002"}],
                        },
                    }
                ]
            },
        ]
        client._client = raw_client

        result = client.fetch_stories_with_subtasks(["SQCRM-7638", "SQCRM-7637", "SQCRM-7639"])

        self.assertEqual([story.key for story, _subtasks in result], ["SQCRM-7638", "SQCRM-7637", "SQCRM-7639"])
        self.assertEqual([subtask.key for subtask in result[1][1]], ["SQCRM-8001"])
        self.assertEqual([subtask.key for subtask in result[2][1]], ["SQCRM-8002"])
        self.assertEqual(raw_client._get_json.call_count, 2)


if __name__ == "__main__":
    unittest.main()
