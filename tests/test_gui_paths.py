import unittest
from pathlib import Path
from unittest.mock import patch

from equalizador_promax.gui import global_secret_path, global_state_dir


class GuiPathTests(unittest.TestCase):
    @patch("equalizador_promax.gui.default_config_path")
    def test_gui_paths_are_stored_under_global_app_directory(self, mocked_default_config_path) -> None:
        mocked_default_config_path.return_value = Path(r"C:\Users\lucas\AppData\Roaming\EqualizadorProMax\config.toml")

        self.assertEqual(global_state_dir(), Path(r"C:\Users\lucas\AppData\Roaming\EqualizadorProMax"))
        self.assertEqual(global_secret_path(), Path(r"C:\Users\lucas\AppData\Roaming\EqualizadorProMax\gui-secret.txt"))


if __name__ == "__main__":
    unittest.main()
