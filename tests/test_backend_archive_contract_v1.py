from __future__ import annotations

import json
import unittest

from backend_archive_contract_v1 import ArchiveContractError, build_archive_record
from archive_fixtures import sample_report


def final_sample_report() -> dict[str, object]:
	report = sample_report()
	report["package"]["file_count"] = 1
	return report


class BackendArchiveContractV1Tests(unittest.TestCase):
	def test_accepts_self_consistent_report(self) -> None:
		payload = build_archive_record(final_sample_report())
		self.assertEqual(payload["package"]["file_count"], 1)
		self.assertEqual(len(payload["files"]), 1)

	def test_rejects_report_count_mismatch(self) -> None:
		report = final_sample_report()
		report["package"]["file_count"] = 999
		with self.assertRaisesRegex(ArchiveContractError, "count mismatch"):
			build_archive_record(report)

	def test_rejects_local_path_hidden_in_allowed_skin_value(self) -> None:
		report = final_sample_report()
		report["validation"]["checks"]["skin_precheck"].update(
			{
				"status": "confirm",
				"item_count": 1,
				"items": [
					{
						"id": r"G:\Branches\secret\skin.dtxml",
						"long_term_status": {"ID": r"G:\Branches\secret\skin.dtxml"},
						"promotions": [],
					}
				],
			}
		)
		with self.assertRaisesRegex(ArchiveContractError, "Local absolute path"):
			build_archive_record(report)

	def test_rejects_local_path_in_region_key_scope_or_warning(self) -> None:
		mutations = (
			lambda report: report["input"]["region_filter"]["excluded_by_region"].update(
				{r"G:\Branches\secret": 1}
			),
			lambda report: report["validation"]["checks"]["commit_record"]["comparison"].update(
				{"scope_roots": [r"G:\Branches\secret"]}
			),
			lambda report: report["validation"]["checks"]["commit_record"]["warnings"][0].update(
				{"fixed_path": r"G:\Branches\secret"}
			),
		)
		for mutate in mutations:
			with self.subTest(mutate=mutate):
				report = final_sample_report()
				mutate(report)
				with self.assertRaises(ArchiveContractError):
					build_archive_record(report)

	def test_rejects_invalid_check_entries(self) -> None:
		mutations = (
			lambda report: report["validation"]["checks"].update({"bad type!": {"status": "passed"}}),
			lambda report: report["validation"]["checks"]["skin_precheck"].update(
				{"status": "unknown_status"}
			),
			lambda report: report["validation"]["checks"]["skin_precheck"].update({"item_count": -1}),
			lambda report: report["validation"]["checks"]["skin_precheck"].update(
				{"tables": "道具信息表"}
			),
		)
		for mutate in mutations:
			with self.subTest(mutate=mutate):
				report = final_sample_report()
				mutate(report)
				with self.assertRaises(ArchiveContractError):
					build_archive_record(report)

	def test_rejects_unsafe_package_identity_and_windows_filenames(self) -> None:
		for field, value in (
			("package_id", "x" * 129),
			("name", "CON"),
			("name", "archive?.tar.gz"),
			("name", "archive.tar.gz."),
		):
			with self.subTest(field=field, value=value):
				report = final_sample_report()
				if field == "package_id":
					report[field] = value
				else:
					report["package"][field] = value
				with self.assertRaises(ArchiveContractError):
					build_archive_record(report)

	def test_final_payload_contains_no_forbidden_transport_fields(self) -> None:
		payload = build_archive_record(final_sample_report())
		serialized = json.dumps(payload, ensure_ascii=False)
		for forbidden in (
			"svn_password",
			"svn_username",
			"svn_log_text",
			"raw_line",
			"local_path",
			"ftp_status",
			"archive_status",
			"mail_status",
		):
			self.assertNotIn(forbidden, serialized)

	def test_preserves_validation_rule_metadata_and_strips_message(self) -> None:
		report = final_sample_report()
		report["validation"]["rule_set"] = {
			"rule_set_id": "aov-main",
			"version": "2026.07.27.1",
			"rule_hash": "a" * 64,
			"published_at": "2026-07-27T13:00:00Z",
			"region_code": "TW",
			"source": "remote",
			"message": "must not be archived",
		}

		payload = build_archive_record(report)
		rule_set = payload["validation"]["rule_set"]
		self.assertEqual("2026.07.27.1", rule_set["version"])
		self.assertEqual("a" * 64, rule_set["rule_hash"])
		self.assertNotIn("message", rule_set)

	def test_acknowledgments_default_to_empty_list(self) -> None:
		payload = build_archive_record(final_sample_report())
		self.assertEqual(payload["validation"]["acknowledgments"], [])

	def test_acknowledgments_survive_normalization(self) -> None:
		report = final_sample_report()
		report["validation"]["acknowledgments"] = [
			{
				"type": "skin_precheck",
				"name": "皮肤促销窗口预检",
				"acknowledged_at": "2026-09-04T10:00:00+08:00",
				"operator_note": "dropped",
			},
			{"type": "expiry_time_cross_check", "acknowledged_at": "2026-09-04T10:01:00+08:00"},
		]

		payload = build_archive_record(report)

		self.assertEqual(
			payload["validation"]["acknowledgments"],
			[
				{
					"type": "skin_precheck",
					"name": "皮肤促销窗口预检",
					"acknowledged_at": "2026-09-04T10:00:00+08:00",
				},
				{
					"type": "expiry_time_cross_check",
					"name": "expiry_time_cross_check",
					"acknowledged_at": "2026-09-04T10:01:00+08:00",
				},
			],
		)

	def test_acknowledgments_reject_malformed_entries(self) -> None:
		for acknowledgments in (
			{"type": "skin_precheck"},
			[{"type": "skin_precheck"}],
			[{"type": "", "acknowledged_at": "2026-09-04T10:00:00Z"}],
			[{"type": "skin_precheck", "acknowledged_at": " "}],
		):
			report = final_sample_report()
			report["validation"]["acknowledgments"] = acknowledgments
			with self.assertRaises(ArchiveContractError):
				build_archive_record(report)


if __name__ == "__main__":
	unittest.main()
