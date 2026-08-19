from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from backend_archive_contract_v1 import ArchiveContractError, build_archive_record
from test_backend_archive_contract_v1 import final_sample_report


class BackendArchiveContractV1FixedPathTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		schema_path = Path(__file__).parent / "schemas" / "aov-package-archive-v1-final.schema.json"
		schema = json.loads(schema_path.read_text(encoding="utf-8"))
		cls.fixed_path_pattern = re.compile(schema["$defs"]["final_fixed_path"]["pattern"])

	def test_builder_rejects_non_normalized_fixed_paths(self) -> None:
		for fixed_path in ("/Taiwan/../secret.xml", "/Taiwan/./file.xml", "/Taiwan//file.xml", "/Taiwan/"):
			with self.subTest(fixed_path=fixed_path):
				report = final_sample_report()
				report["files"][0]["fixed_path"] = fixed_path
				with self.assertRaisesRegex(ArchiveContractError, "fixed path"):
					build_archive_record(report)

	def test_schema_rejects_non_normalized_fixed_paths(self) -> None:
		for fixed_path in ("/Taiwan/../secret.xml", "/Taiwan/./file.xml", "/Taiwan//file.xml", "/Taiwan/"):
			with self.subTest(fixed_path=fixed_path):
				self.assertIsNone(self.fixed_path_pattern.fullmatch(fixed_path))

	def test_root_and_normal_path_remain_valid(self) -> None:
		for fixed_path in ("/", "/Taiwan", "/sgame/gamedata/Taiwan/file.xml"):
			with self.subTest(fixed_path=fixed_path):
				self.assertIsNotNone(self.fixed_path_pattern.fullmatch(fixed_path))


if __name__ == "__main__":
	unittest.main()
