"""package_completeness 规则（rules.impl.package_completeness）单元测试。"""
from __future__ import annotations

import unittest

from rules.impl.package_completeness import run_package_completeness
from rules.registry import default_incident_content_checks


class PackageCompletenessTests(unittest.TestCase):
    def _check(self) -> dict[str, object]:
        return next(
            check for check in default_incident_content_checks()
            if check["type"] == "package_completeness"
        )

    def test_manual_mode_missing_files_warns_with_paths(self) -> None:
        result = run_package_completeness(
            fixed_paths=["/Taiwan/Databin/Server/Item/SvrItem.bytes", "/Taiwan/Databin/Server/Shop/Shop.bytes"],
            validation_config={"commit_record": {"input_method": "pasted_svn_file_list"}},
            package_files=[
                {"fixed_path": "/Taiwan/Databin/Server/Item/SvrItem.bytes", "status": "packaged", "size": 4096},
                {"fixed_path": "/Taiwan/Databin/Server/Shop/Shop.bytes", "status": "failed"},
            ],
            check=self._check(),
        )
        self.assertEqual("warning", result["status"])
        types = [warning["type"] for warning in result["warnings"]]
        self.assertIn("package_files_failed", types)
        self.assertIn("package_count_mismatch", types)

    def test_manual_mode_empty_package_warns(self) -> None:
        result = run_package_completeness(
            fixed_paths=["/Taiwan/Databin/Server/Item/SvrItem.bytes"],
            validation_config={"commit_record": {"input_method": "pasted_svn_file_list"}},
            package_files=[{"fixed_path": "/Taiwan/Databin/Server/Item/SvrItem.bytes", "status": "packaged", "size": 10}],
            check=self._check(),
        )
        self.assertEqual("warning", result["status"])
        self.assertEqual("package_suspected_empty", result["warnings"][0]["type"])
        self.assertIn("核对打包路径配置", result["warnings"][0]["message"])

    def test_manual_mode_complete_package_passes(self) -> None:
        result = run_package_completeness(
            fixed_paths=["/Taiwan/Databin/Server/Item/SvrItem.bytes"],
            validation_config={"commit_record": {"input_method": "pasted_svn_file_list"}},
            package_files=[{"fixed_path": "/Taiwan/Databin/Server/Item/SvrItem.bytes", "status": "packaged", "size": 2048}],
            check=self._check(),
        )
        self.assertEqual("passed", result["status"])

    def test_svn_mode_is_skipped(self) -> None:
        result = run_package_completeness(
            fixed_paths=["/Taiwan/Databin/Server/Item/SvrItem.bytes"],
            validation_config={"commit_record": {"input_method": "revision_spec"}},
            package_files=[],
            check=self._check(),
        )
        self.assertEqual("skipped", result["status"])
        self.assertEqual("svn_mode_covered_by_commit_record", result["reason"])


if __name__ == "__main__":
    unittest.main()
