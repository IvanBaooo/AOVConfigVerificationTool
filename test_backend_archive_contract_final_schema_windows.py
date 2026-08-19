from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


class BackendArchiveContractFinalSchemaWindowsTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		schema_path = Path(__file__).parent / "schemas" / "aov-package-archive-v1-final.schema.json"
		schema = json.loads(schema_path.read_text(encoding="utf-8"))
		cls.filename_pattern = re.compile(schema["$defs"]["windows_filename"]["pattern"])

	def test_windows_reserved_names_are_case_insensitive(self) -> None:
		for filename in ("CON", "con.txt", "CoM1.log", "lPt9.xml"):
			with self.subTest(filename=filename):
				self.assertIsNone(self.filename_pattern.fullmatch(filename))

	def test_normal_filename_is_allowed(self) -> None:
		self.assertIsNotNone(self.filename_pattern.fullmatch("sgame_TW_Beta54_20260713.tar.gz"))


if __name__ == "__main__":
	unittest.main()
