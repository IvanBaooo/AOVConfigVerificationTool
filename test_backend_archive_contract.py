from __future__ import annotations

import json
import unittest

from backend_archive_contract import (
	ARCHIVE_CONTRACT_VERSION,
	ArchiveContractError,
	archive_create_headers,
	build_archive_record,
)
from test_backend_archive_payload import sample_report


class BackendArchiveContractTests(unittest.TestCase):
	def test_builds_immutable_archive_record(self) -> None:
		payload = build_archive_record(sample_report())

		self.assertEqual(payload["schema_version"], ARCHIVE_CONTRACT_VERSION)
		self.assertEqual(payload["record_type"], "aov_package_archive")
		self.assertEqual(
			set(payload["status"]),
			{"package_status", "validation_status"},
		)
		serialized = json.dumps(payload, ensure_ascii=False)
		self.assertNotIn("ftp_status", serialized)
		self.assertNotIn("archive_status", serialized)
		self.assertNotIn("mail_status", serialized)

	def test_nested_skin_details_use_explicit_field_allowlist(self) -> None:
		report = sample_report()
		skin = report["validation"]["checks"]["skin_precheck"]
		skin.update(
			{
				"status": "confirm",
				"item_count": 1,
				"items": [
					{
						"type": "skin_precheck_confirm",
						"level": "confirm",
						"table": "英雄皮肤促销表",
						"id": "1001",
						"skin_id": "2001",
						"skin_name": "Sample Skin",
						"long_term_status": {
							"上架时间": "20260701000000",
							"售卖方式": "point",
							"svn_password": "nested-secret",
							"local_path": r"G:\Branches\secret\skin.dtxml",
						},
						"promotions": [
							{
								"promo_id": "3001",
								"fields": {
									"促销特卖ID": "3001",
									"下架时间": "20260731235959",
									"svn_log_text": "nested-secret",
								},
							}
						],
					}
				],
			}
		)

		payload = build_archive_record(report)
		serialized = json.dumps(payload, ensure_ascii=False)

		self.assertIn("上架时间", serialized)
		self.assertIn("促销特卖ID", serialized)
		self.assertNotIn("nested-secret", serialized)
		self.assertNotIn("svn_password", serialized)
		self.assertNotIn("svn_log_text", serialized)
		self.assertNotIn(r"G:\Branches", serialized)

	def test_invalid_numbers_are_rejected_instead_of_coerced(self) -> None:
		for field, invalid_value in (
			("file_count", -1),
			("failed_count", True),
			("skipped_count", "not-a-number"),
		):
			with self.subTest(field=field):
				report = sample_report()
				report["package"][field] = invalid_value
				with self.assertRaisesRegex(ArchiveContractError, field):
					build_archive_record(report)

	def test_duplicate_or_non_positive_revisions_are_rejected(self) -> None:
		for revisions in ([1699997, 1699997], [0], [-1], [True]):
			with self.subTest(revisions=revisions):
				report = sample_report()
				report["validation"]["checks"]["commit_record"]["current_package"]["revisions"] = revisions
				with self.assertRaisesRegex(ArchiveContractError, "current_revisions"):
					build_archive_record(report)

	def test_artifacts_must_be_plain_filenames(self) -> None:
		report = sample_report()
		report["package"]["report_file"] = r"G:\Branches\secret\report.json"

		with self.assertRaisesRegex(ArchiveContractError, "report_file"):
			build_archive_record(report)

	def test_idempotency_key_is_safe_for_http_header(self) -> None:
		report = sample_report()
		report["idempotency_key"] = "bad\r\nInjected: value"

		with self.assertRaisesRegex(ArchiveContractError, "idempotency_key"):
			build_archive_record(report)

		payload = build_archive_record(sample_report())
		headers = archive_create_headers(payload)
		self.assertEqual(headers["Idempotency-Key"], payload["idempotency_key"])


if __name__ == "__main__":
	unittest.main()
