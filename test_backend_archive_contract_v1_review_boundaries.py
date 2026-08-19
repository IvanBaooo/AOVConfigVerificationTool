from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from backend_archive_contract_v1 import ArchiveContractError, build_archive_record
from test_backend_archive_contract_v1 import final_sample_report


def report_with_skin_id(value: str) -> dict[str, object]:
	report = final_sample_report()
	report["validation"]["checks"]["skin_precheck"].update(
		{
			"status": "confirm",
			"item_count": 1,
			"items": [
				{
					"id": value,
					"long_term_status": {"ID": value},
					"promotions": [],
				}
			],
		}
	)
	return report


class BackendArchiveContractV1ReviewBoundaryTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		root = Path(__file__).parent
		schema = json.loads(
			(root / "schemas" / "aov-package-archive-v1-final.schema.json").read_text(encoding="utf-8")
		)
		cls.package_id_pattern = re.compile(
			schema["allOf"][1]["properties"]["package_id"]["pattern"]
		)
		cls.contract_doc = (root / "BACKEND_ARCHIVE_CONTRACT_CURRENT.md").read_text(encoding="utf-8")

	def test_rejects_windows_root_and_forward_slash_unc_paths(self) -> None:
		for value in (r"\Users\admin\secret.xml", "//server/share/secret.xml"):
			with self.subTest(value=value):
				with self.assertRaisesRegex(ArchiveContractError, "Local absolute path"):
					build_archive_record(report_with_skin_id(value))

	def test_package_id_cannot_be_dot_path_segment(self) -> None:
		for value in (".", ".."):
			with self.subTest(value=value):
				report = final_sample_report()
				report["package_id"] = value
				with self.assertRaisesRegex(ArchiveContractError, "package_id"):
					build_archive_record(report)
				self.assertIsNone(self.package_id_pattern.fullmatch(value))

	def test_contract_defines_server_replay_and_conflict_semantics(self) -> None:
		for expected in (
			"unique database constraint",
			"Idempotency-Replayed: true",
			"409 idempotency_conflict",
			"409 package_id_conflict",
		):
			with self.subTest(expected=expected):
				self.assertIn(expected, self.contract_doc)


if __name__ == "__main__":
	unittest.main()
