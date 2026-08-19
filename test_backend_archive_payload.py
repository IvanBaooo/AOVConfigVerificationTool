from __future__ import annotations

import json
import unittest

from backend_archive_payload import (
	ARCHIVE_CONTRACT_VERSION,
	ArchivePayloadError,
	archive_request_headers,
	build_archive_payload,
)


def sample_report() -> dict[str, object]:
	return {
		"schema_version": "0.1",
		"package_id": "sgame_TW_Beta54_20260713153524",
		"idempotency_key": "sgame_TW_Beta54_20260713153524",
		"created_at": "2026-07-13T15:35:24+08:00",
		"input": {
			"archive_root": "/sgame/gamedata",
			"region_filter": {
				"enabled": True,
				"region_code": "TW",
				"region_dir": "Taiwan",
				"original_count": 54,
				"included_count": 20,
				"excluded_count": 34,
				"excluded_unknown_count": 0,
				"excluded_by_region": {"Thailand": 2, "Vietnam": 2},
			},
			"svn_username": "must-not-leak",
			"svn_password": "must-not-leak",
			"svn_log_text": "must-not-leak",
		},
		"status": {
			"package_status": "success",
			"validation_status": "passed",
			"ftp_status": "not_required",
			"archive_status": "not_started",
			"mail_status": "not_required",
		},
		"package": {
			"name": "sgame_TW_Beta54_20260713153524.tar.gz",
			"md5": "a158b202c61906ad4adc97f88597ac74",
			"sha256": "e062d33a0820b392b1737372c63d9d1510cfca6d8684adc3540b7d85464315fe",
			"list_file": "sgame_TW_Beta54_20260713153524.list.txt",
			"md5_file": "sgame_TW_Beta54_20260713153524.md5.txt",
			"report_file": "sgame_TW_Beta54_20260713153524.report.json",
			"file_count": 20,
			"failed_count": 0,
			"skipped_count": 0,
		},
		"files": [
			{
				"action": "M",
				"fixed_path": "/Taiwan/Databin/Server/Shop/SvrSpecialSale.xml",
				"archive_path": "/sgame/gamedata/Taiwan/Databin/Server/Shop/SvrSpecialSale.xml",
				"raw_line": "M ServerBytes/Taiwan/Databin/Server/Shop/SvrSpecialSale.xml",
				"local_path": r"G:\Branches\secret\SvrSpecialSale.xml",
				"status": "packaged",
				"local_exists": True,
				"size": 39351,
				"mtime": "2026-07-07T17:02:01+08:00",
			},
		],
		"validation": {
			"summary": {
				"error_count": 0,
				"warning_count": 1,
				"confirm_count": 0,
				"skipped_count": 1,
			},
			"checks": {
				"commit_record": {
					"status": "warning",
					"input_method": "revision_spec",
					"last_external": {
						"time": "2026-07-01T10:00:00+08:00",
						"revision_spec": "r1698349",
						"revisions": [1698349],
					},
					"current_package": {
						"revision_spec": "r1699919,r1699997",
						"revisions": [1699919, 1699997],
						"package_path_count": 20,
					},
					"comparison": {
						"expected_revision_spec": "r1698350-r1699997",
						"included_revision_spec": "r1699919,r1699997",
						"excluded_revision_spec": "r1698350-r1699918,r1699920-r1699996",
						"scope_roots": ["/Taiwan"],
					},
					"warning_count": 1,
					"warnings": [
						{
							"type": "unpackaged_change_between_releases",
							"level": "warning",
							"table_name": "Hero_MD5",
							"readable_name": "Hero_MD5.txt",
							"directory": "/Taiwan/Databin/Server/Actor",
							"file_name": "Hero_MD5.txt",
							"fixed_path": "/Taiwan/Databin/Server/Actor/Hero_MD5.txt",
							"revisions": [1698418],
							"actions": ["M"],
							"message": "unpackaged readable table warning",
							"svn_username": "must-not-leak",
						},
					],
					"statistics": {
						"svn_log_returned_revision_count": 64,
						"svn_log_min_revision": 1698363,
						"svn_log_max_revision": 1699997,
						"filtered_unresolved_revision_count": 1584,
						"whitelisted_warning_count": 3,
						"whitelisted_paths": ["/Taiwan/Databin/Server/Actor/Hero_MD5.txt"],
					},
				},
				"skin_precheck": {
					"status": "skipped",
					"reason": "missing_check_window",
					"source": {
						"dtxml": r"G:\Branches\secret\skin.dtxml",
						"xml": r"G:\Branches\secret\skin.xml",
						"xml_exists": True,
						"main_sheet": "main",
						"promo_sheet": "promo",
					},
					"items": [],
					"warnings": [],
				},
			},
		},
		"naming": {
			"region_code": "TW",
			"package_version": "Beta54",
			"timestamp": "20260713153524",
		},
	}


class BackendArchivePayloadTests(unittest.TestCase):
	def test_builds_v1_archive_payload_from_report(self) -> None:
		payload = build_archive_payload(sample_report())

		self.assertEqual(payload["schema_version"], ARCHIVE_CONTRACT_VERSION)
		self.assertEqual(payload["record_type"], "aov_package_archive")
		self.assertEqual(payload["release"]["region_code"], "TW")
		self.assertEqual(payload["release"]["package_version"], "Beta54")
		self.assertEqual(payload["release"]["current_revisions"], [1699919, 1699997])
		self.assertEqual(payload["package"]["file_count"], 20)
		self.assertEqual(payload["region_filter"]["excluded_count"], 34)
		self.assertEqual(payload["validation"]["commit_record"]["warnings"][0]["table_name"], "Hero_MD5")
		self.assertEqual(payload["validation"]["commit_record"]["whitelist_hit_count"], 3)
		self.assertEqual(payload["files"][0]["fixed_path"], "/Taiwan/Databin/Server/Shop/SvrSpecialSale.xml")

	def test_payload_excludes_credentials_raw_svn_and_local_paths(self) -> None:
		serialized = json.dumps(build_archive_payload(sample_report()), ensure_ascii=False)

		for forbidden in (
			"must-not-leak",
			"svn_password",
			"svn_username",
			"svn_log_text",
			"raw_line",
			"local_path",
			r"G:\Branches\secret",
		):
			self.assertNotIn(forbidden, serialized)

	def test_archive_headers_reuse_report_idempotency_key(self) -> None:
		payload = build_archive_payload(sample_report())
		headers = archive_request_headers(payload)

		self.assertEqual(headers["Idempotency-Key"], "sgame_TW_Beta54_20260713153524")
		self.assertEqual(headers["X-AOV-Contract-Version"], ARCHIVE_CONTRACT_VERSION)
		self.assertEqual(headers["Content-Type"], "application/json")

	def test_missing_required_identity_is_rejected(self) -> None:
		report = sample_report()
		report["idempotency_key"] = ""

		with self.assertRaisesRegex(ArchivePayloadError, "idempotency_key"):
			build_archive_payload(report)


if __name__ == "__main__":
	unittest.main()
