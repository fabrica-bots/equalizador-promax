import tempfile
import unittest
from pathlib import Path

from equalizador_promax.config import AppConfig, JiraSettings, load_config, save_config


class ConfigTests(unittest.TestCase):
    def test_load_config_creates_default_file_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"

            loaded = load_config(config_path)

            self.assertTrue(config_path.exists())
            self.assertEqual(loaded.jira.base_url, "https://agile.corp.edp.pt")
            self.assertEqual(loaded.jira.auth_mode, "token")
            self.assertEqual(loaded.jira.credential_account, "")

    def test_save_and_load_config_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config = AppConfig(
                jira=JiraSettings(
                    base_url="https://jira.example",
                    auth_mode="token",
                    username=None,
                    credential_service="equalizador-promax/jira",
                    credential_account="lucas",
                    timeout_seconds=30,
                ),
                config_path=config_path,
            )

            save_config(config, config_path)
            loaded = load_config(config_path)

            self.assertEqual(loaded.jira.base_url, "https://jira.example")
            self.assertEqual(loaded.jira.auth_mode, "token")
            self.assertEqual(loaded.jira.credential_account, "lucas")
            self.assertEqual(loaded.jira.timeout_seconds, 30)


if __name__ == "__main__":
    unittest.main()
