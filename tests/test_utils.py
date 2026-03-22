import unittest
from datetime import datetime
from pathlib import Path

from equalizador_promax.utils import (
    build_release_branch_name,
    calculate_fingerprint,
    extract_issue_keys,
    generate_run_id,
)


class UtilsTests(unittest.TestCase):
    def test_generate_run_id_uses_repo_slug(self) -> None:
        run_id = generate_run_id("Meu Repo", now=datetime(2026, 3, 21, 10, 30, 45))
        self.assertEqual(run_id, "20260321-103045-meu-repo")

    def test_calculate_fingerprint_is_order_independent(self) -> None:
        first = calculate_fingerprint(Path("C:/repo"), ["SQCRM-2", "SQCRM-1"])
        second = calculate_fingerprint(Path("C:/repo"), ["SQCRM-1", "SQCRM-2", "SQCRM-2"])
        self.assertEqual(first, second)

    def test_extract_issue_keys(self) -> None:
        self.assertEqual(
            extract_issue_keys("Merge PR 9 - SQCRM-10 com AJUSTE-4"),
            {"SQCRM-10", "AJUSTE-4"},
        )

    def test_build_release_branch_name(self) -> None:
        branch_name = build_release_branch_name(
            "Versão Release 58",
            now=datetime(2026, 3, 21, 21, 20, 50),
        )
        self.assertEqual(branch_name, "equalizacao/versao_release_58_21-03-2026-21-20-50")

    def test_build_release_branch_name_replaces_invalid_chars_with_dash(self) -> None:
        branch_name = build_release_branch_name(
            "Versão Release 58 / QBR:94",
            now=datetime(2026, 3, 21, 21, 20, 50),
        )
        self.assertEqual(branch_name, "equalizacao/versao_release_58-qbr-94_21-03-2026-21-20-50")


if __name__ == "__main__":
    unittest.main()
