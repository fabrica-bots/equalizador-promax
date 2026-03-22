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


if __name__ == "__main__":
    unittest.main()
