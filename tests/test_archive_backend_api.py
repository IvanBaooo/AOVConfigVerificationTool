from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from archive_backend.api import ArchiveApplication
from archive_backend.repository import ArchiveRepository
from archive_backend.schema_validation import ArchivePayloadValidator
from backend_archive_contract_v1 import build_archive_record
from test_backend_archive_contract_v1 import final_sample_report


class ArchiveApplicationTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		repository = ArchiveRepository(Path(self.temp_dir.name) / "archives.sqlite3")
		self.application = ArchiveApplication(
			repository=repository,
			validator=ArchivePayloadValidator(),
			access_token="unit-test-token",
		)

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def payload(self) -> dict[str, object]:
		return build_archive_record(final_sample_report())

	def request(
		self,
		method: str,
		path: str,
		*,
		payload: dict[str, object] | None = None,
		headers: dict[str, str] | None = None,
		authorized: bool = True,
	):
		request_headers = dict(headers or {})
		if authorized:
			request_headers.setdefault("Authorization", "Bearer unit-test-token")
		body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
		return self.application.handle(method, path, request_headers, body)

	def archive_headers(self, payload: dict[str, object]) -> dict[str, str]:
		return {
			"Content-Type": "application/json; charset=utf-8",
			"Idempotency-Key": payload["idempotency_key"],
			"X-AOV-Contract-Version": "1.0",
		}

	def test_health_is_public_but_archive_routes_require_bearer_token(self) -> None:
		health = self.request("GET", "/health", authorized=False)
		unauthorized = self.request("GET", "/api/v1/package-archives", authorized=False)

		self.assertEqual(health.status, 200)
		self.assertEqual(health.body["status"], "ok")
		self.assertTrue(health.body["auth_required"])
		self.assertEqual(unauthorized.status, 401)
		self.assertEqual(unauthorized.body["error"]["code"], "unauthorized")

	def test_no_auth_mode_allows_local_api_requests(self) -> None:
		application = ArchiveApplication(
			repository=self.application.repository,
			validator=ArchivePayloadValidator(),
			access_token=None,
		)

		health = application.handle("GET", "/health", {})
		listing = application.handle("GET", "/api/v1/package-archives", {})

		self.assertFalse(health.body["auth_required"])
		self.assertEqual(listing.status, 200)

	def test_dashboard_summary_requires_auth_and_returns_all_regions(self) -> None:
		payload = self.payload()
		self.request(
			"POST",
			"/api/v1/package-archives",
			payload=payload,
			headers=self.archive_headers(payload),
		)

		unauthorized = self.request("GET", "/api/v1/dashboard-summary", authorized=False)
		response = self.request("GET", "/api/v1/dashboard-summary")
		bad_query = self.request("GET", "/api/v1/dashboard-summary?region_code=TW")

		self.assertEqual(unauthorized.status, 401)
		self.assertEqual(response.status, 200)
		self.assertEqual(response.body["overview"]["active_count"], 1)
		self.assertEqual(
			[item["region_code"] for item in response.body["regions"]],
			["TW", "TH", "VN", "ID"],
		)
		self.assertEqual(response.body["regions"][0]["baseline"]["package_id"], payload["package_id"])
		self.assertEqual(bad_query.status, 400)

	def test_create_replay_list_and_get_archive(self) -> None:
		payload = self.payload()
		headers = self.archive_headers(payload)

		created = self.request("POST", "/api/v1/package-archives", payload=payload, headers=headers)
		replayed = self.request("POST", "/api/v1/package-archives", payload=payload, headers=headers)
		listing = self.request("GET", "/api/v1/package-archives?region_code=TW&limit=10")
		detail = self.request("GET", f"/api/v1/package-archives/{payload['package_id']}")

		self.assertEqual(created.status, 201)
		self.assertEqual(created.body["result"], "created")
		self.assertEqual(replayed.status, 200)
		self.assertEqual(replayed.headers["Idempotency-Replayed"], "true")
		self.assertEqual(listing.body["total"], 1)
		self.assertEqual(detail.body["archive"], payload)

	def test_admin_can_soft_delete_restore_and_read_audit(self) -> None:
		payload = self.payload()
		self.request(
			"POST",
			"/api/v1/package-archives",
			payload=payload,
			headers=self.archive_headers(payload),
		)

		deleted = self.request(
			"POST",
			f"/api/v1/admin/package-archives/{payload['package_id']}/soft-delete",
			payload={"reason": "重复归档"},
			headers={"Content-Type": "application/json"},
		)
		active_list = self.request("GET", "/api/v1/package-archives")
		deleted_list = self.request("GET", "/api/v1/package-archives?record_state=deleted")
		detail = self.request("GET", f"/api/v1/package-archives/{payload['package_id']}")

		self.assertEqual(deleted.status, 200)
		self.assertEqual(deleted.body["event"]["actor"], "admin")
		self.assertEqual(active_list.body["total"], 0)
		self.assertEqual(deleted_list.body["total"], 1)
		self.assertEqual(detail.body["management"]["record_state"], "deleted")

		restored = self.request(
			"POST",
			f"/api/v1/admin/package-archives/{payload['package_id']}/restore",
			payload={"reason": "确认保留"},
			headers={"Content-Type": "application/json"},
		)
		audit = self.request("GET", "/api/v1/admin/archive-audit")
		filtered_audit = self.request(
			"GET",
			"/api/v1/admin/archive-audit?action=delete&region_code=TW",
		)

		self.assertEqual(restored.body["result"], "restored")
		self.assertEqual(audit.body["total"], 2)
		self.assertEqual(audit.body["items"][0]["action"], "restore")
		self.assertEqual(audit.body["items"][0]["region_code"], "TW")
		self.assertEqual(filtered_audit.body["total"], 1)
		self.assertEqual(filtered_audit.body["items"][0]["action"], "delete")

	def test_admin_management_requires_reason_and_valid_state(self) -> None:
		payload = self.payload()
		self.request(
			"POST",
			"/api/v1/package-archives",
			payload=payload,
			headers=self.archive_headers(payload),
		)
		path = f"/api/v1/admin/package-archives/{payload['package_id']}/soft-delete"

		missing_reason = self.request(
			"POST",
			path,
			payload={"reason": "  "},
			headers={"Content-Type": "application/json"},
		)
		self.request(
			"POST",
			path,
			payload={"reason": "清理"},
			headers={"Content-Type": "application/json"},
		)
		duplicate = self.request(
			"POST",
			path,
			payload={"reason": "重复"},
			headers={"Content-Type": "application/json"},
		)
		bad_filter = self.request("GET", "/api/v1/package-archives?record_state=unknown")
		bad_audit_filter = self.request("GET", "/api/v1/admin/archive-audit?action=unknown")

		self.assertEqual(missing_reason.status, 422)
		self.assertEqual(duplicate.status, 409)
		self.assertEqual(duplicate.body["error"]["code"], "archive_already_deleted")
		self.assertEqual(bad_filter.status, 400)
		self.assertEqual(bad_audit_filter.status, 400)

	def test_delete_current_baseline_requires_and_applies_replacement(self) -> None:
		first = self.payload()
		self.request(
			"POST",
			"/api/v1/package-archives",
			payload=first,
			headers=self.archive_headers(first),
		)
		second = copy.deepcopy(first)
		second["package_id"] = "sgame_TW_Beta54_20260714120000"
		second["idempotency_key"] = second["package_id"]
		second["created_at"] = "2026-07-14T12:00:00+08:00"
		self.request(
			"POST",
			"/api/v1/package-archives",
			payload=second,
			headers=self.archive_headers(second),
		)
		path = f"/api/v1/admin/package-archives/{second['package_id']}/soft-delete"

		missing = self.request(
			"POST",
			path,
			payload={"reason": "撤回错误归档"},
			headers={"Content-Type": "application/json"},
		)
		deleted = self.request(
			"POST",
			path,
			payload={
				"reason": "撤回错误归档",
				"replacement_package_id": first["package_id"],
			},
			headers={"Content-Type": "application/json"},
		)
		baseline = self.request("GET", "/api/v1/release-baselines/latest?region_code=TW")

		self.assertEqual(missing.status, 409)
		self.assertEqual(missing.body["error"]["code"], "baseline_replacement_required")
		self.assertEqual(deleted.status, 200)
		self.assertEqual(deleted.body["event"]["baseline"]["package_id"], first["package_id"])
		self.assertEqual(baseline.body["baseline"]["package_id"], first["package_id"])

	def test_admin_can_explicitly_set_release_baseline(self) -> None:
		first = self.payload()
		self.request(
			"POST",
			"/api/v1/package-archives",
			payload=first,
			headers=self.archive_headers(first),
		)
		second = copy.deepcopy(first)
		second["package_id"] = "sgame_TW_Beta54_20260714120000"
		second["idempotency_key"] = second["package_id"]
		self.request(
			"POST",
			"/api/v1/package-archives",
			payload=second,
			headers=self.archive_headers(second),
		)

		response = self.request(
			"POST",
			"/api/v1/admin/release-baselines/TW",
			payload={"package_id": first["package_id"], "reason": "人工确认回退"},
			headers={"Content-Type": "application/json"},
		)
		listing = self.request("GET", "/api/v1/package-archives?region_code=TW")

		self.assertEqual(response.status, 200)
		self.assertEqual(response.body["baseline"]["package_id"], first["package_id"])
		baseline_items = [item for item in listing.body["items"] if item["is_release_baseline"]]
		self.assertEqual([item["package_id"] for item in baseline_items], [first["package_id"]])

	def test_latest_release_baseline_uses_latest_archived_region_record(self) -> None:
		first = self.payload()
		first_headers = self.archive_headers(first)
		self.request("POST", "/api/v1/package-archives", payload=first, headers=first_headers)

		second = copy.deepcopy(first)
		second["package_id"] = "sgame_TW_Beta54_20260714120000"
		second["idempotency_key"] = second["package_id"]
		second["created_at"] = "2026-07-14T12:00:00+08:00"
		second["release"]["current_revision_spec"] = "r1700001,r1700003"
		second["release"]["current_revisions"] = [1700001, 1700003]
		second_headers = self.archive_headers(second)
		self.request("POST", "/api/v1/package-archives", payload=second, headers=second_headers)

		response = self.request("GET", "/api/v1/release-baselines/latest?region_code=TW")

		self.assertEqual(response.status, 200)
		baseline = response.body["baseline"]
		self.assertEqual(baseline["package_id"], second["package_id"])
		self.assertEqual(baseline["released_revision_spec"], "r1700001,r1700003")
		self.assertEqual(baseline["released_revisions"], [1700001, 1700003])
		self.assertEqual(baseline["last_checked_revision"], 1700003)
		self.assertEqual(baseline["package_created_at"], second["created_at"])
		self.assertTrue(str(baseline["release_time"]).endswith("Z"))

	def test_release_baseline_requires_auth_and_existing_region_archive(self) -> None:
		unauthorized = self.request(
			"GET",
			"/api/v1/release-baselines/latest?region_code=TW",
			authorized=False,
		)
		missing = self.request("GET", "/api/v1/release-baselines/latest?region_code=TH")
		invalid = self.request("GET", "/api/v1/release-baselines/latest?region_code=XX")

		self.assertEqual(unauthorized.status, 401)
		self.assertEqual(missing.status, 404)
		self.assertEqual(missing.body["error"]["code"], "release_baseline_not_found")
		self.assertEqual(invalid.status, 400)

	def test_schema_and_contract_invariants_return_422(self) -> None:
		missing_field = self.payload()
		del missing_field["release"]["region_code"]
		missing_response = self.request(
			"POST",
			"/api/v1/package-archives",
			payload=missing_field,
			headers=self.archive_headers(missing_field),
		)

		local_path = self.payload()
		local_path["validation"]["skin_precheck"].update(
			{
				"status": "confirm",
				"item_count": 1,
				"items": [{"id": "https://example.invalid/?path=C://secret/file.xml"}],
			}
		)
		path_response = self.request(
			"POST",
			"/api/v1/package-archives",
			payload=local_path,
			headers=self.archive_headers(local_path),
		)

		self.assertEqual(missing_response.status, 422)
		self.assertEqual(missing_response.body["error"]["code"], "invalid_payload")
		self.assertEqual(path_response.status, 422)

	def test_header_mismatch_and_conflicts_have_stable_error_codes(self) -> None:
		payload = self.payload()
		wrong_headers = self.archive_headers(payload)
		wrong_headers["Idempotency-Key"] = "wrong-key"
		mismatch = self.request(
			"POST", "/api/v1/package-archives", payload=payload, headers=wrong_headers
		)
		self.assertEqual(mismatch.status, 400)
		self.assertEqual(mismatch.body["error"]["code"], "idempotency_key_mismatch")

		headers = self.archive_headers(payload)
		self.request("POST", "/api/v1/package-archives", payload=payload, headers=headers)
		changed = copy.deepcopy(payload)
		changed["package"]["md5"] = "b" * 32
		conflict = self.request(
			"POST", "/api/v1/package-archives", payload=changed, headers=headers
		)
		self.assertEqual(conflict.status, 409)
		self.assertEqual(conflict.body["error"]["code"], "idempotency_conflict")

	def test_invalid_query_and_unknown_archive_return_client_errors(self) -> None:
		bad_query = self.request("GET", "/api/v1/package-archives?limit=999")
		missing = self.request("GET", "/api/v1/package-archives/not-found")

		self.assertEqual(bad_query.status, 400)
		self.assertEqual(bad_query.body["error"]["code"], "invalid_query")
		self.assertEqual(missing.status, 404)


if __name__ == "__main__":
	unittest.main()
