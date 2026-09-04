from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


class BackendArchiveContractFinalSchemaRegexTests(unittest.TestCase):
	def test_final_schema_patterns_compile(self) -> None:
		schema_path = Path(__file__).parent.parent / "schemas" / "aov-package-archive-v1-final.schema.json"
		schema = json.loads(schema_path.read_text(encoding="utf-8"))

		re.compile(schema["$defs"]["windows_filename"]["pattern"])
		re.compile(schema["$defs"]["final_fixed_path"]["pattern"])


if __name__ == "__main__":
	unittest.main()
