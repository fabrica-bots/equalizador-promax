import unittest
from unittest.mock import Mock

from equalizador_promax.config import AppConfig, JiraSettings
from equalizador_promax.errors import ValidationError
from equalizador_promax.orchestrator import EqualizadorService


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

    def test_resolve_story_keys_rejects_empty_release_result(self) -> None:
        self.service.jira.fetch_release_name.return_value = "Versão Release 58"
        self.service.jira.fetch_release_issue_keys.return_value = []
        with self.assertRaises(ValidationError):
            self.service.resolve_release("59571")


if __name__ == "__main__":
    unittest.main()
