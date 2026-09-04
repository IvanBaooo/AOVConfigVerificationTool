from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend_archive_contract_v1 import build_archive_record
from test_backend_archive_contract_v1 import final_sample_report


class BackendArchiveContractFinalSchemaTests(unittest.TestCase):
	def test_final_schema_overlays_strict_schema(self) -> None:
		schema_path = Path(__file__).parent.parent / "schemas" / "aov-package-archive-v1-final.schema.json"
		schema = json.loads(schema_path.read_text(encoding="utf-8"))

		self.assertEqual(
			schema["allOf"][0]["$ref"],
			"aov-package-archive-v1-strict.schema.json",
		)
		self.assertIn("Windows absolute", schema["x-aov-invariants"][0])

	def test_final_payload_has_only_immutable_statuses(self) -> None:
		payload = build_archive_record(final_sample_report())
		self.assertEqual(set(payload["status"]), {"package_status", "validation_status"})

	def test_final_schema_restricts_region_keys_and_windows_names(self) -> None:
		schema_path = Path(__file__).parent.parent / "schemas" / "aov-package-archive-v1-final.schema.json"
		schema = json.loads(schema_path.read_text(encoding="utf-8"))
		overlay = schema["allOf"][1]["properties"]
		region_names = overlay["region_filter"]["properties"]["excluded_by_region"]["propertyNames"]["enum"]

		self.assertIn("Taiwan", region_names)
		self.assertNotIn(r"G:\Branches\secret", region_names)
		self.assertIn("CON", schema["$defs"]["windows_filename"]["pattern"])


if __name__ == "__main__":
	unittest.main()
