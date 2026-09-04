from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend_archive_contract_v1 import (
	ArchiveContractError,
	archive_create_headers,
	build_archive_record,
)
from test_backend_archive_contract_v1 import final_sample_report


class BackendArchiveContractV1SendBoundaryTests(unittest.TestCase):
	def test_archive_root_uses_final_fixed_path_rules(self) -> None:
		for archive_root in ("/sgame/../secret", "/sgame//gamedata", "/sgame/gamedata/"):
			with self.subTest(archive_root=archive_root):
				report = final_sample_report()
				report["input"]["archive_root"] = archive_root
				with self.assertRaisesRegex(ArchiveContractError, "fixed path"):
					build_archive_record(report)

	def test_send_headers_reject_mutable_status_fields(self) -> None:
		for mutable_status in ("ftp_status", "archive_status", "mail_status"):
			with self.subTest(mutable_status=mutable_status):
				payload = build_archive_record(final_sample_report())
				payload["status"][mutable_status] = "success"
				with self.assertRaisesRegex(ArchiveContractError, "status"):
					archive_create_headers(payload)

	def test_final_schema_overlays_archive_root(self) -> None:
		schema_path = Path(__file__).parent.parent / "schemas" / "aov-package-archive-v1-final.schema.json"
		schema = json.loads(schema_path.read_text(encoding="utf-8"))
		archive_root = schema["allOf"][1]["properties"]["package"]["properties"]["archive_root"]
		self.assertEqual(archive_root["$ref"], "#/$defs/final_fixed_path")

	def test_invalid_rule_hash_is_rejected_at_send_boundary(self) -> None:
		report = final_sample_report()
		report["validation"]["rule_set"] = {
			"rule_set_id": "aov-main",
			"version": "1",
			"rule_hash": "invalid",
			"published_at": "2026-07-27T13:00:00Z",
			"region_code": "TW",
			"source": "remote",
		}

		with self.assertRaisesRegex(ArchiveContractError, "rule_hash"):
			build_archive_record(report)


if __name__ == "__main__":
	unittest.main()
