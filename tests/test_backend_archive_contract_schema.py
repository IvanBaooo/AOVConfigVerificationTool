from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend_archive_contract import IDEMPOTENCY_PATTERN, build_archive_record
from archive_fixtures import sample_report


class BackendArchiveContractSchemaTests(unittest.TestCase):
	def test_strict_schema_closes_sensitive_nested_objects(self) -> None:
		schema_path = Path(__file__).parent.parent / "schemas" / "aov-package-archive-v1-strict.schema.json"
		schema = json.loads(schema_path.read_text(encoding="utf-8"))

		self.assertFalse(schema["additionalProperties"])
		self.assertFalse(schema["$defs"]["commit_record"]["additionalProperties"])
		self.assertFalse(schema["$defs"]["commit_warning"]["additionalProperties"])
		self.assertFalse(schema["$defs"]["check_entry"]["additionalProperties"])
		self.assertFalse(schema["$defs"]["file"]["additionalProperties"])
		self.assertNotIn("skin_precheck", schema["$defs"])
		self.assertNotIn("skin_item", schema["$defs"])
		self.assertNotIn("skin_fields", schema["$defs"])
		self.assertEqual(
			schema["properties"]["validation"]["required"],
			["rule_set", "summary", "commit_record", "checks"],
		)

	def test_schema_and_builder_share_idempotency_pattern(self) -> None:
		schema_path = Path(__file__).parent.parent / "schemas" / "aov-package-archive-v1-strict.schema.json"
		schema = json.loads(schema_path.read_text(encoding="utf-8"))
		self.assertEqual(
			schema["properties"]["idempotency_key"]["pattern"],
			IDEMPOTENCY_PATTERN.pattern,
		)

	def test_builder_status_matches_immutable_schema(self) -> None:
		report = sample_report()
		report["package"]["file_count"] = 1
		payload = build_archive_record(report)
		schema_path = Path(__file__).parent.parent / "schemas" / "aov-package-archive-v1-strict.schema.json"
		schema = json.loads(schema_path.read_text(encoding="utf-8"))

		self.assertEqual(set(payload["status"]), set(schema["properties"]["status"]["properties"]))
		self.assertEqual(set(payload), set(schema["properties"]))


if __name__ == "__main__":
	unittest.main()
