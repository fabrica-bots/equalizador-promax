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
                        "id": "10001",
                        "key": "SQCRM-7637",
                        "fields": {
                            "issuetype": {"name": "story"},
                            "subtasks": [{"id": "10002", "key": "SQCRM-8001"}],
                        },
                    },
                    {
                        "id": "10003",
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
                        "id": "10004",
                        "key": "SQCRM-7639",
                        "fields": {
                            "issuetype": {"name": "story"},
                            "subtasks": [{"id": "10005", "key": "SQCRM-8002"}],
                        },
                    }
                ]
            },
        ]
        client._client = raw_client

        result = client.fetch_stories_with_subtasks(["SQCRM-7638", "SQCRM-7637", "SQCRM-7639"])

        self.assertEqual([story.key for story, _subtasks in result], ["SQCRM-7638", "SQCRM-7637", "SQCRM-7639"])
        self.assertEqual(result[1][0].issue_id, "10001")
        self.assertEqual([subtask.key for subtask in result[1][1]], ["SQCRM-8001"])
        self.assertEqual(result[1][1][0].issue_id, "10002")
        self.assertEqual([subtask.key for subtask in result[2][1]], ["SQCRM-8002"])
        self.assertEqual(raw_client._get_json.call_count, 2)

    def test_fetch_pull_requests_for_issues_uses_dev_status_and_parses_branches(self) -> None:
        client = JiraClient(JiraSettings(base_url="https://jira.example", auth_mode="token"))
        raw_client = Mock()
        raw_client._get_json.return_value = {
            "errors": [],
            "detail": [
                {
                    "pullRequests": [
                        {
                            "id": "58",
                            "name": "Release 58",
                            "url": "https://git.example/pr/58",
                            "status": "MERGED",
                            "source": {"branch": "feature/SQCRM-7691"},
                            "destination": {"branch": "quality"},
                        }
                    ]
                }
            ],
        }
        client._client = raw_client

        result = client.fetch_pull_requests_for_issues({"SQCRM-7691": "10001"})

        pull_request = result["SQCRM-7691"][0]
        self.assertEqual(pull_request.pr_id, "58")
        self.assertEqual(pull_request.status, "MERGED")
        self.assertEqual(pull_request.source_branch, "feature/SQCRM-7691")
        self.assertEqual(pull_request.destination_branch, "quality")
        raw_client._get_json.assert_called_once()
        _path, kwargs = raw_client._get_json.call_args
        self.assertEqual(kwargs["params"]["issueId"], "10001")
        self.assertEqual(kwargs["params"]["applicationType"], "stash")
        self.assertEqual(kwargs["params"]["dataType"], "pullrequest")
        self.assertIn("/rest/dev-status/1.0/", kwargs["base"])

    def test_fetch_pull_requests_for_issue_keys_uses_gitplugin_and_parses_github_payload(self) -> None:
        client = JiraClient(JiraSettings(base_url="https://jira.example", auth_mode="token"))
        raw_client = Mock()
        raw_client._get_json.return_value = {
            "success": True,
            "pullRequests": {
                "items": [
                    {
                        "id": "161",
                        "state": "MERGED",
                        "title": "SQCRM-7691 - Mapeamento edpb2c_tipo_precificacao_flex no negocio",
                        "baseBranch": "quality",
                        "compareBranch": "equalizacao/bravo_release_58_00",
                        "url": "https://github.com/GitHub-EDP/msdyn-crm-b2b-webresources/pull/161",
                        "repository": {"id": 18467, "name": "msdyn-crm-b2b-webresources"},
                    }
                ]
            },
        }
        client._client = raw_client

        result = client.fetch_pull_requests_for_issue_keys(["sqcrm-7691"])

        pull_request = result["SQCRM-7691"][0]
        self.assertEqual(pull_request.pr_id, "161")
        self.assertEqual(pull_request.status, "MERGED")
        self.assertEqual(pull_request.source_branch, "equalizacao/bravo_release_58_00")
        self.assertEqual(pull_request.destination_branch, "quality")
        self.assertEqual(pull_request.repository_name, "msdyn-crm-b2b-webresources")
        raw_client._get_json.assert_called_once()
        path, kwargs = raw_client._get_json.call_args
        self.assertEqual(path[0], "issuegitdetails/issue/SQCRM-7691/pullRequest")
        self.assertIn("/rest/gitplugin/1.0/", kwargs["base"])


if __name__ == "__main__":
    unittest.main()
