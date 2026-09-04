from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from archive_backend.api import ArchiveApplication
from archive_backend.repository import ArchiveRepository
from archive_backend.schema_validation import ArchivePayloadValidator
from backend_archive_contract_v1 import build_archive_record
from test_backend_archive_contract_v1 import final_sample_report


class ArchiveReviewMigrationTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		self.database_path = Path(self.temp_dir.name) / "archives.sqlite3"

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def _legacy_row(
		self,
		connection: sqlite3.Connection,
		package_id: str,
		payload: dict[str, object],
		validation_status: str,
	) -> None:
		connection.execute(
			"""
			INSERT INTO package_archives (
				package_id, schema_version, idempotency_key, payload_sha256, payload_json,
				created_at, received_at, region_code, region_dir, package_version,
				package_status, validation_status, file_count, warning_count
			) VALUES (?, '1.0', ?, '', ?, '2026-07-01T08:00:00Z', '2026-07-01T08:00:00Z',
				'TW', 'Taiwan', 'Beta54', 'success', ?, 1, 0)
			""",
			(package_id, package_id, json.dumps(payload), validation_status),
		)

	def _create_legacy_db(self) -> None:
		connection = sqlite3.connect(self.database_path)
		try:
			connection.executescript(
				"""
				CREATE TABLE package_archives (
					package_id TEXT PRIMARY KEY,
					schema_version TEXT NOT NULL,
					idempotency_key TEXT NOT NULL,
					payload_sha256 TEXT NOT NULL,
					payload_json TEXT NOT NULL,
					created_at TEXT NOT NULL,
					received_at TEXT NOT NULL,
					region_code TEXT NOT NULL,
					region_dir TEXT NOT NULL,
					package_version TEXT NOT NULL,
					package_status TEXT NOT NULL,
					validation_status TEXT NOT NULL,
					file_count INTEGER NOT NULL,
					warning_count INTEGER NOT NULL,
					UNIQUE (schema_version, idempotency_key)
				);
				"""
			)
			self._legacy_row(
				connection,
				"legacy-warning",
				{"validation": {"checks": [{"type": "commit_record", "status": "warning"}]}},
				"warning",
			)
			self._legacy_row(
				connection,
				"legacy-passed",
				{"validation": {"checks": [
					{"type": "commit_record", "status": "passed"},
					{"type": "skin_precheck", "status": "skipped"},
				]}},
				"passed",
			)
			self._legacy_row(connection, "legacy-no-checks-warning", {"validation": {}}, "warning")
			self._legacy_row(connection, "legacy-no-checks-passed", {"validation": {}}, "passed")
			connection.commit()
		finally:
			connection.close()

	def _migrated_items(self) -> dict[str, dict[str, object]]:
		repository = ArchiveRepository(self.database_path)
		return {
			item["package_id"]: item
			for item in repository.list_archives(record_state="all")["items"]
		}

	def test_migration_backfills_review_status(self) -> None:
		self._create_legacy_db()

		items = self._migrated_items()

		self.assertEqual(items["legacy-warning"]["review_status"], "pending_review")
		self.assertIsNone(items["legacy-warning"]["reviewed_at"])
		self.assertIsNone(items["legacy-warning"]["reviewed_by"])
		self.assertEqual(items["legacy-passed"]["review_status"], "confirmed")
		self.assertEqual(items["legacy-passed"]["reviewed_at"], "2026-07-01T08:00:00Z")
		self.assertEqual(items["legacy-passed"]["reviewed_by"], "migration")
		self.assertEqual(items["legacy-no-checks-warning"]["review_status"], "pending_review")
		self.assertEqual(items["legacy-no-checks-passed"]["review_status"], "confirmed")

	def test_migration_is_idempotent_on_reopen(self) -> None:
		self._create_legacy_db()
		first = self._migrated_items()

		second = self._migrated_items()

		self.assertEqual(first, second)


class ArchiveReviewCreateTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		self.repository = ArchiveRepository(Path(self.temp_dir.name) / "archives.sqlite3")

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def payload(self) -> dict[str, object]:
		return build_archive_record(final_sample_report())

	def test_warning_check_marks_pending_review(self) -> None:
		payload = self.payload()
		for check in payload["validation"]["checks"]:
			if check["type"] == "hidden_item_listing":
				check["status"] = "warning"
				check["warning_count"] = 1

		result = self.repository.create_archive(payload)

		self.assertEqual(result.summary["review_status"], "pending_review")
		self.assertIsNone(result.summary["reviewed_at"])
		self.assertIsNone(result.summary["reviewed_by"])

	def test_confirm_check_marks_pending_review(self) -> None:
		payload = self.payload()
		for check in payload["validation"]["checks"]:
			check["status"] = "passed"
		payload["validation"]["checks"][0]["status"] = "confirm"

		result = self.repository.create_archive(payload)

		self.assertEqual(result.summary["review_status"], "pending_review")

	def test_all_passed_checks_auto_confirm(self) -> None:
		payload = self.payload()
		for check in payload["validation"]["checks"]:
			check["status"] = "passed"

		result = self.repository.create_archive(payload)

		self.assertEqual(result.summary["review_status"], "confirmed")
		self.assertEqual(result.summary["reviewed_by"], "auto")
		self.assertEqual(result.summary["reviewed_at"], result.summary["received_at"])


class ArchiveReviewConfirmApiTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		self.repository = ArchiveRepository(Path(self.temp_dir.name) / "archives.sqlite3")
		self.application = ArchiveApplication(
			repository=self.repository,
			validator=ArchivePayloadValidator(),
			access_token="review-test-token",
		)

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def create_archive(self, payload: dict[str, object]) -> None:
		response = self.application.handle(
			"POST",
			"/api/v1/package-archives",
			{
				"Authorization": "Bearer review-test-token",
				"Content-Type": "application/json",
				"Idempotency-Key": payload["idempotency_key"],
				"X-AOV-Contract-Version": "1.0",
			},
			json.dumps(payload, ensure_ascii=False).encode("utf-8"),
		)
		self.assertEqual(response.status, 201)

	def confirm(self, package_id: str, body: dict[str, object] | None = None, authorized: bool = True):
		headers = {"Content-Type": "application/json"}
		if authorized:
			headers["Authorization"] = "Bearer review-test-token"
		return self.application.handle(
			"POST",
			f"/api/v1/admin/package-archives/{package_id}/review-confirm",
			headers,
			json.dumps(body if body is not None else {}, ensure_ascii=False).encode("utf-8"),
		)

	def pending_archive(self) -> dict[str, object]:
		payload = build_archive_record(final_sample_report())
		for check in payload["validation"]["checks"]:
			if check["type"] == "hidden_item_listing":
				check["status"] = "warning"
				check["warning_count"] = 1
		self.create_archive(payload)
		return payload

	def test_confirm_pending_archive_with_note_writes_audit(self) -> None:
		payload = self.pending_archive()

		response = self.confirm(payload["package_id"], {"note": "人工确认无误"})

		self.assertEqual(response.status, 200)
		self.assertEqual(response.body["result"], "confirmed")
		self.assertNotIn("Idempotency-Replayed", response.headers)
		review = response.body["review"]
		self.assertEqual(review["review_status"], "confirmed")
		self.assertEqual(review["reviewed_by"], "admin")
		self.assertTrue(review["reviewed_at"])
		self.assertEqual(review["note"], "人工确认无误")

		audit = self.repository.list_archive_audit(action="review_confirm")
		self.assertEqual(audit["total"], 1)
		self.assertEqual(audit["items"][0]["actor"], "admin")
		self.assertEqual(audit["items"][0]["reason"], "人工确认无误")
		management = self.repository.get_archive_management(payload["package_id"])
		self.assertEqual(management["review_status"], "confirmed")
		self.assertEqual(management["reviewed_by"], "admin")
		self.assertEqual(management["review_note"], "人工确认无误")

	def test_repeat_confirm_is_replayed_without_new_audit(self) -> None:
		payload = self.pending_archive()
		self.confirm(payload["package_id"], {"note": "首次确认"})

		response = self.confirm(payload["package_id"], {"note": "重复确认"})

		self.assertEqual(response.status, 200)
		self.assertEqual(response.body["result"], "replayed")
		self.assertEqual(response.headers["Idempotency-Replayed"], "true")
		self.assertEqual(response.body["review"]["reviewed_by"], "admin")
		self.assertEqual(self.repository.list_archive_audit(action="review_confirm")["total"], 1)
		management = self.repository.get_archive_management(payload["package_id"])
		self.assertEqual(management["review_note"], "首次确认")

	def test_confirm_auto_confirmed_archive_is_replayed(self) -> None:
		payload = build_archive_record(final_sample_report())
		for check in payload["validation"]["checks"]:
			check["status"] = "passed"
		self.create_archive(payload)

		response = self.confirm(payload["package_id"])

		self.assertEqual(response.status, 200)
		self.assertEqual(response.body["result"], "replayed")
		self.assertEqual(response.body["review"]["reviewed_by"], "auto")
		self.assertEqual(self.repository.list_archive_audit(action="review_confirm")["total"], 0)

	def test_confirm_unknown_archive_returns_404(self) -> None:
		response = self.confirm("sgame_TW_Beta54_20990101000000")

		self.assertEqual(response.status, 404)
		self.assertEqual(response.body["error"]["code"], "archive_not_found")

	def test_confirm_rejects_invalid_note(self) -> None:
		payload = self.pending_archive()

		non_string = self.confirm(payload["package_id"], {"note": 123})
		too_long = self.confirm(payload["package_id"], {"note": "x" * 501})

		self.assertEqual(non_string.status, 422)
		self.assertEqual(too_long.status, 422)
		self.assertEqual(
			self.repository.get_archive_management(payload["package_id"])["review_status"],
			"pending_review",
		)

	def test_confirm_requires_auth_and_get_is_not_allowed(self) -> None:
		payload = self.pending_archive()

		unauthorized = self.confirm(payload["package_id"], authorized=False)
		wrong_method = self.application.handle(
			"GET",
			f"/api/v1/admin/package-archives/{payload['package_id']}/review-confirm",
			{"Authorization": "Bearer review-test-token"},
		)

		self.assertEqual(unauthorized.status, 401)
		self.assertEqual(wrong_method.status, 405)

	def test_audit_action_filter_accepts_review_confirm(self) -> None:
		payload = self.pending_archive()
		self.confirm(payload["package_id"], {"note": "复核通过"})

		response = self.application.handle(
			"GET",
			"/api/v1/admin/archive-audit?action=review_confirm",
			{"Authorization": "Bearer review-test-token"},
		)

		self.assertEqual(response.status, 200)
		self.assertEqual(response.body["total"], 1)
		self.assertEqual(response.body["items"][0]["action"], "review_confirm")

	def test_dashboard_summary_counts_pending_review(self) -> None:
		pending = self.pending_archive()
		confirmed = build_archive_record(final_sample_report())
		confirmed["package_id"] = "sgame_TW_Beta54_20260714120000"
		confirmed["idempotency_key"] = confirmed["package_id"]
		confirmed["created_at"] = "2026-07-14T12:00:00+08:00"
		for check in confirmed["validation"]["checks"]:
			check["status"] = "passed"
		self.create_archive(confirmed)

		before = self.application.handle(
			"GET",
			"/api/v1/dashboard-summary",
			{"Authorization": "Bearer review-test-token"},
		)
		self.assertEqual(before.body["overview"]["pending_review_count"], 1)

		self.confirm(pending["package_id"])

		after = self.application.handle(
			"GET",
			"/api/v1/dashboard-summary",
			{"Authorization": "Bearer review-test-token"},
		)
		self.assertEqual(after.body["overview"]["pending_review_count"], 0)


if __name__ == "__main__":
	unittest.main()
