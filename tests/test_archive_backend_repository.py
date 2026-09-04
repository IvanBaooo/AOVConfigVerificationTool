from __future__ import annotations

import copy
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from archive_backend.repository import ArchiveConflict, ArchiveRepository
from backend_archive_contract_v1 import build_archive_record
from rules.sets import validate_rule_set
from test_backend_archive_contract_v1 import final_sample_report
from test_validation_rule_sets import sample_rule_set


class ArchiveRepositoryTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		self.repository = ArchiveRepository(Path(self.temp_dir.name) / "archives.sqlite3")

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def payload(self) -> dict[str, object]:
		return build_archive_record(final_sample_report())

	def test_create_then_replay_semantically_identical_payload(self) -> None:
		payload = self.payload()
		created = self.repository.create_archive(payload)
		reordered = dict(reversed(list(payload.items())))
		replayed = self.repository.create_archive(reordered)

		self.assertEqual(created.result, "created")
		self.assertEqual(replayed.result, "replayed")
		self.assertEqual(created.summary["package_id"], payload["package_id"])
		self.assertEqual(self.repository.get_archive(payload["package_id"]), payload)

	def test_same_idempotency_key_with_different_payload_conflicts(self) -> None:
		payload = self.payload()
		self.repository.create_archive(payload)
		changed = copy.deepcopy(payload)
		changed["package"]["md5"] = "b" * 32

		with self.assertRaises(ArchiveConflict) as caught:
			self.repository.create_archive(changed)

		self.assertEqual(caught.exception.code, "idempotency_conflict")

	def test_same_package_id_under_different_key_conflicts(self) -> None:
		payload = self.payload()
		self.repository.create_archive(payload)
		changed = copy.deepcopy(payload)
		changed["idempotency_key"] = "different-idempotency-key"

		with self.assertRaises(ArchiveConflict) as caught:
			self.repository.create_archive(changed)

		self.assertEqual(caught.exception.code, "package_id_conflict")

	def test_list_supports_filters_and_pagination(self) -> None:
		first = self.payload()
		self.repository.create_archive(first)
		second = copy.deepcopy(first)
		second["package_id"] = "sgame_TH_Beta54_20260713160000"
		second["idempotency_key"] = second["package_id"]
		second["release"]["region_code"] = "TH"
		second["release"]["region_dir"] = "Thailand"
		second["status"]["validation_status"] = "warning"
		self.repository.create_archive(second)

		thai = self.repository.list_archives(region_code="TH", validation_status="warning")
		page = self.repository.list_archives(limit=1, offset=1)

		self.assertEqual(thai["total"], 1)
		self.assertEqual(thai["items"][0]["package_id"], second["package_id"])
		self.assertEqual(page["total"], 2)
		self.assertEqual(len(page["items"]), 1)

	def test_soft_delete_restore_and_audit_preserve_archive_payload(self) -> None:
		payload = self.payload()
		self.repository.create_archive(payload)

		deleted = self.repository.soft_delete_archive(
			payload["package_id"],
			actor="admin",
			reason="重复归档",
		)

		self.assertEqual(deleted["action"], "delete")
		self.assertEqual(self.repository.list_archives()["total"], 0)
		deleted_list = self.repository.list_archives(record_state="deleted")
		self.assertEqual(deleted_list["total"], 1)
		self.assertEqual(deleted_list["items"][0]["deleted_by"], "admin")
		self.assertEqual(deleted_list["items"][0]["delete_reason"], "重复归档")
		self.assertEqual(self.repository.get_archive(payload["package_id"]), payload)

		management = self.repository.get_archive_management(payload["package_id"])
		self.assertEqual(management["record_state"], "deleted")
		self.repository.restore_archive(
			payload["package_id"],
			actor="admin",
			reason="确认保留",
		)

		self.assertEqual(self.repository.list_archives()["total"], 1)
		self.assertEqual(self.repository.list_archives(record_state="deleted")["total"], 0)
		audit = self.repository.list_archive_audit()
		self.assertEqual(audit["total"], 2)
		self.assertEqual([item["action"] for item in audit["items"]], ["restore", "delete"])
		self.assertEqual(audit["items"][0]["actor"], "admin")
		self.assertEqual(audit["items"][0]["region_code"], "TW")
		deleted_audit = self.repository.list_archive_audit(action="delete", region_code="TW")
		self.assertEqual(deleted_audit["total"], 1)
		self.assertEqual(deleted_audit["items"][0]["action"], "delete")

	def test_soft_delete_and_restore_reject_invalid_current_state(self) -> None:
		payload = self.payload()
		self.repository.create_archive(payload)

		with self.assertRaises(ArchiveConflict) as restore_error:
			self.repository.restore_archive(payload["package_id"], actor="admin", reason="恢复")
		self.assertEqual(restore_error.exception.code, "archive_not_deleted")

		self.repository.soft_delete_archive(payload["package_id"], actor="admin", reason="删除")
		with self.assertRaises(ArchiveConflict) as delete_error:
			self.repository.soft_delete_archive(payload["package_id"], actor="admin", reason="再次删除")
		self.assertEqual(delete_error.exception.code, "archive_already_deleted")

	def test_release_baseline_requires_explicit_replacement_when_deleted(self) -> None:
		first = self.payload()
		self.repository.create_archive(first)
		second = copy.deepcopy(first)
		second["package_id"] = "sgame_TW_Beta54_20260714120000"
		second["idempotency_key"] = second["package_id"]
		second["created_at"] = "2026-07-14T12:00:00+08:00"
		second["release"]["current_revision_spec"] = "r1700001"
		second["release"]["current_revisions"] = [1700001]
		self.repository.create_archive(second)

		self.assertEqual(
			self.repository.get_latest_release_baseline("TW")["package_id"],
			second["package_id"],
		)
		with self.assertRaises(ArchiveConflict) as caught:
			self.repository.soft_delete_archive(
				second["package_id"],
				actor="admin",
				reason="撤回错误归档",
			)
		self.assertEqual(caught.exception.code, "baseline_replacement_required")

		event = self.repository.soft_delete_archive(
			second["package_id"],
			actor="admin",
			reason="撤回错误归档",
			replacement_package_id=first["package_id"],
		)
		self.assertTrue(event["baseline"]["changed"])
		self.assertEqual(event["baseline"]["package_id"], first["package_id"])
		self.assertEqual(
			self.repository.get_latest_release_baseline("TW")["package_id"],
			first["package_id"],
		)

		self.repository.restore_archive(second["package_id"], actor="admin", reason="恢复记录")
		self.assertEqual(
			self.repository.get_latest_release_baseline("TW")["package_id"],
			first["package_id"],
		)
		self.repository.set_release_baseline(second["package_id"], actor="admin", reason="确认重新对外")
		self.assertEqual(
			self.repository.get_latest_release_baseline("TW")["package_id"],
			second["package_id"],
		)
		items = self.repository.list_archives()["items"]
		baseline_items = [item for item in items if item["is_release_baseline"]]
		self.assertEqual([item["package_id"] for item in baseline_items], [second["package_id"]])

	def test_release_baseline_replacement_must_be_active_and_same_region(self) -> None:
		first = self.payload()
		self.repository.create_archive(first)
		thai = copy.deepcopy(first)
		thai["package_id"] = "sgame_TH_Beta54_20260714120000"
		thai["idempotency_key"] = thai["package_id"]
		thai["release"]["region_code"] = "TH"
		thai["release"]["region_dir"] = "Thailand"
		self.repository.create_archive(thai)

		with self.assertRaises(ArchiveConflict) as caught:
			self.repository.soft_delete_archive(
				first["package_id"],
				actor="admin",
				reason="错误替换",
				replacement_package_id=thai["package_id"],
			)
		self.assertEqual(caught.exception.code, "invalid_baseline_replacement")

	def test_dashboard_summary_combines_regions_baselines_and_recent_archives(self) -> None:
		first = self.payload()
		self.repository.create_archive(first)
		second = copy.deepcopy(first)
		second["package_id"] = "sgame_TH_Beta54_20260714120000"
		second["idempotency_key"] = second["package_id"]
		second["release"]["region_code"] = "TH"
		second["release"]["region_dir"] = "Thailand"
		self.repository.create_archive(second)
		self.repository.soft_delete_archive(second["package_id"], actor="admin", reason="撤回")

		summary = self.repository.get_dashboard_summary(("TW", "TH", "VN", "ID"))

		self.assertEqual(summary["overview"]["active_count"], 1)
		self.assertEqual(summary["overview"]["deleted_count"], 1)
		self.assertEqual(summary["overview"]["baseline_count"], 1)
		self.assertEqual([item["region_code"] for item in summary["regions"]], ["TW", "TH", "VN", "ID"])
		self.assertEqual(summary["regions"][0]["baseline"]["package_id"], first["package_id"])
		self.assertIsNone(summary["regions"][1]["baseline"])
		self.assertEqual(summary["recent_archives"][0]["package_id"], first["package_id"])

	def test_concurrent_retries_create_only_one_row(self) -> None:
		payload = self.payload()

		with ThreadPoolExecutor(max_workers=8) as executor:
			results = list(executor.map(lambda _: self.repository.create_archive(payload).result, range(8)))

		self.assertEqual(results.count("created"), 1)
		self.assertEqual(results.count("replayed"), 7)
		self.assertEqual(self.repository.list_archives()["total"], 1)

	def test_list_archives_filters_by_received_date_range(self) -> None:
		first = self.payload()
		self.repository.create_archive(first)
		second = copy.deepcopy(first)
		second["package_id"] = "sgame_TH_Beta54_20260714120000"
		second["idempotency_key"] = second["package_id"]
		second["release"]["region_code"] = "TH"
		second["release"]["region_dir"] = "Thailand"
		self.repository.create_archive(second)

		today = datetime.now(timezone.utc).date()
		yesterday = (today - timedelta(days=1)).isoformat()
		tomorrow = (today + timedelta(days=1)).isoformat()

		both = self.repository.list_archives(
			received_from=today.isoformat(),
			received_to=today.isoformat(),
		)
		future = self.repository.list_archives(received_from=tomorrow)
		past = self.repository.list_archives(received_to=yesterday)

		self.assertEqual(both["total"], 2)
		self.assertEqual(future["total"], 0)
		self.assertEqual(past["total"], 0)

	def test_activity_by_day_counts_archives_rules_and_baseline_events(self) -> None:
		payload = self.payload()
		self.repository.create_archive(payload)
		self.repository.set_release_baseline(payload["package_id"], actor="admin", reason="首次对外")
		today = datetime.now(timezone.utc).date().isoformat()
		rule_set = sample_rule_set()
		rule_set["published_at"] = f"{today}T08:00:00Z"
		self.repository.publish_rule_set(validate_rule_set(rule_set))

		activity = self.repository.activity_by_day(7)
		today_entry = activity["days"][-1]

		self.assertEqual(len(activity["days"]), 7)
		self.assertEqual(today_entry["date"], today)
		self.assertEqual(today_entry["archives"], 1)
		self.assertEqual(
			today_entry["warnings"],
			int(payload["validation"]["summary"]["warning_count"]),
		)
		self.assertEqual(today_entry["rule_publishes"], 1)
		self.assertEqual(today_entry["baseline_changes"], 1)
		self.assertEqual(activity["days"][0]["archives"], 0)
		self.assertEqual(activity["days"][0]["rule_publishes"], 0)
		self.assertIsNone(activity["region_code"])

	def test_activity_by_day_filters_by_region(self) -> None:
		first = self.payload()
		self.repository.create_archive(first)
		second = copy.deepcopy(first)
		second["package_id"] = "sgame_TH_Beta54_20260714120000"
		second["idempotency_key"] = second["package_id"]
		second["release"]["region_code"] = "TH"
		second["release"]["region_dir"] = "Thailand"
		self.repository.create_archive(second)
		self.repository.set_release_baseline(first["package_id"], actor="admin", reason="首次对外")

		filtered = self.repository.activity_by_day(7, "TW")
		overall = self.repository.activity_by_day(7)

		self.assertEqual(filtered["region_code"], "TW")
		self.assertEqual(filtered["days"][-1]["archives"], 1)
		self.assertEqual(filtered["days"][-1]["baseline_changes"], 1)
		self.assertEqual(overall["days"][-1]["archives"], 2)

	def test_activity_by_day_rejects_non_positive_days(self) -> None:
		with self.assertRaises(ValueError):
			self.repository.activity_by_day(0)


if __name__ == "__main__":
	unittest.main()
