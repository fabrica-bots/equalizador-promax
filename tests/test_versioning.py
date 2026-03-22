import tempfile
import unittest
from pathlib import Path

from equalizador_promax.versioning import (
    increment_patch_version,
    read_current_version,
    version_to_windows_tuple,
    write_version,
)


class VersioningTests(unittest.TestCase):
    def test_increment_patch_version(self) -> None:
        self.assertEqual(increment_patch_version("0.1.0"), "0.1.1")

    def test_version_to_windows_tuple(self) -> None:
        self.assertEqual(version_to_windows_tuple("1.2.3"), (1, 2, 3, 0))

    def test_write_version_updates_all_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "src" / "equalizador_promax").mkdir(parents=True)
            (root / "installer").mkdir(parents=True)

            (root / "src" / "equalizador_promax" / "version.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
            (root / "pyproject.toml").write_text('version = "0.1.0"\n', encoding="utf-8")
            (root / "installer" / "EqualizadorProMax.iss").write_text('#define MyAppVersion "0.1.0"\n', encoding="utf-8")
            (root / "installer" / "version-info.txt").write_text(
                'filevers=(0, 1, 0, 0)\n'
                'prodvers=(0, 1, 0, 0)\n'
                'StringStruct("FileVersion", "0.1.0")\n'
                'StringStruct("ProductVersion", "0.1.0")\n',
                encoding="utf-8",
            )

            write_version(root, "0.1.1")

            self.assertEqual(read_current_version(root), "0.1.1")
            self.assertIn('version = "0.1.1"', (root / "pyproject.toml").read_text(encoding="utf-8"))
            self.assertIn('#define MyAppVersion "0.1.1"', (root / "installer" / "EqualizadorProMax.iss").read_text(encoding="utf-8"))
            version_info = (root / "installer" / "version-info.txt").read_text(encoding="utf-8")
            self.assertIn("filevers=(0, 1, 1, 0)", version_info)
            self.assertIn('StringStruct("FileVersion", "0.1.1")', version_info)


if __name__ == "__main__":
    unittest.main()
