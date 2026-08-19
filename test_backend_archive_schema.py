from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend_archive_payload import build_archive_payload
from test_backend_archive_payload import sample_report


class BackendArchiveSchemaTests(unittest.TestCase):
	def test_builder_top_level_matches_schema_properties(self) -> None:
		schema_path = Path(__file__).parent / "schemas" / "aov-package-archive-v1.schema.json"
		schema = json.loads(schema_path.read_text(encoding="utf-8"))
		payload = build_archive_payload(sample_report())

		self.assertEqual(set(payload), set(schema["properties"]))
		self.assertTrue(set(schema["required"]).issubset(payload))
		self.assertEqual(payload["schema_version"], schema["properties"]["schema_version"]["const"])
		self.assertEqual(payload["record_type"], schema["properties"]["record_type"]["const"])

	def test_strict_nested_groups_match_schema_properties(self) -> None:
		schema_path = Path(__file__).parent / "schemas" / "aov-package-archive-v1.schema.json"
		schema = json.loads(schema_path.read_text(encoding="utf-8"))
		payload = build_archive_payload(sample_report())

		for group in ("release", "package", "status", "region_filter"):
			with self.subTest(group=group):
				expected = set(schema["properties"][group]["properties"])
				self.assertEqual(set(payload[group]), expected)

		file_properties = set(schema["properties"]["files"]["items"]["properties"])
		for item in payload["files"]:
			self.assertTrue(set(item).issubset(file_properties))


if __name__ == "__main__":
	unittest.main()
