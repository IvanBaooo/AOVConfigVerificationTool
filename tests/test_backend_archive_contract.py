from __future__ import annotations

import json
import unittest

from backend_archive_contract import (
	ARCHIVE_CONTRACT_VERSION,
	ArchiveContractError,
	archive_create_headers,
	build_archive_record,
)
from backend_archive_contract.base import CHECK_DETAIL_LIST_LIMIT
from archive_fixtures import check_entry, sample_report


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

	def test_checks_dict_becomes_generic_check_entries(self) -> None:
		payload = build_archive_record(sample_report())
		validation = payload["validation"]

		self.assertNotIn("skin_precheck", validation)
		checks = validation["checks"]
		self.assertEqual(
			{"hidden_item_listing", "skin_precheck"},
			{entry["type"] for entry in checks},
		)
		hidden = check_entry(payload, "hidden_item_listing")
		self.assertEqual(
			set(hidden),
			{"type", "name", "status", "item_count", "warning_count", "tables", "items", "warnings"},
		)
		self.assertEqual("隐藏道具识别与单独标注", hidden["name"])
		self.assertEqual(["道具信息表"], hidden["tables"])

		# 皮肤预检降级为普通一条，专属字段（check_window/source）不再归档
		skin = check_entry(payload, "skin_precheck")
		self.assertEqual("skipped", skin["status"])
		self.assertEqual([], skin["tables"])
		serialized = json.dumps(skin, ensure_ascii=False)
		self.assertNotIn("check_window", serialized)
		self.assertNotIn("source", serialized)

	def test_check_entry_falls_back_to_registry_metadata(self) -> None:
		report = sample_report()
		report["validation"]["checks"]["expiry_time_cross_check"] = {
			"status": "warning",
			"warning_count": 1,
			"warnings": [{"message": "expire before activity start"}],
		}

		payload = build_archive_record(report)
		entry = check_entry(payload, "expiry_time_cross_check")

		self.assertEqual("道具有效期与活动时间关联校验", entry["name"])
		self.assertEqual(["道具信息表", "活动表"], entry["tables"])
		self.assertEqual(0, entry["item_count"])
		self.assertEqual(1, entry["warning_count"])

	def test_check_entry_items_and_warnings_are_capped(self) -> None:
		report = sample_report()
		report["validation"]["checks"]["hidden_item_listing"].update(
			{
				"status": "confirm",
				"item_count": CHECK_DETAIL_LIST_LIMIT + 5,
				"warning_count": CHECK_DETAIL_LIST_LIMIT + 5,
				"items": [{"item_id": str(i)} for i in range(CHECK_DETAIL_LIST_LIMIT + 5)],
				"warnings": [{"message": f"w{i}"} for i in range(CHECK_DETAIL_LIST_LIMIT + 5)],
			}
		)

		payload = build_archive_record(report)
		entry = check_entry(payload, "hidden_item_listing")

		self.assertEqual(CHECK_DETAIL_LIST_LIMIT, len(entry["items"]))
		self.assertEqual(CHECK_DETAIL_LIST_LIMIT, len(entry["warnings"]))
		# 计数保留原始全量，不被截断影响
		self.assertEqual(CHECK_DETAIL_LIST_LIMIT + 5, entry["item_count"])
		self.assertEqual(CHECK_DETAIL_LIST_LIMIT + 5, entry["warning_count"])

	def test_check_details_strip_sensitive_keys_recursively(self) -> None:
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
