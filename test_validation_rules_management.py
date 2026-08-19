from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from archive_backend.api import ArchiveApplication
from archive_backend.repository import ArchiveRepository
from archive_backend.schema_validation import ArchivePayloadValidator
from archive_backend.server import _is_loopback_address
from test_validation_rule_sets import sample_rule_set


class ValidationRulesManagementTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		self.application = ArchiveApplication(
			repository=ArchiveRepository(Path(self.temp_dir.name) / "archives.sqlite3"),
			validator=ArchivePayloadValidator(),
			access_token="management-token",
		)

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def publish(self, payload: dict[str, object]):
		return self.application.handle(
			"POST",
			"/api/v1/validation-rule-sets",
			{
				"Authorization": "Bearer management-token",
				"Content-Type": "application/json",
			},
			json.dumps(payload, ensure_ascii=False).encode("utf-8"),
		)

	def test_history_and_detail_are_public_read_only_routes(self) -> None:
		self.assertEqual(201, self.publish(sample_rule_set()).status)

		history = self.application.handle(
			"GET",
			"/api/v1/validation-rule-sets?limit=20&offset=0",
			{},
		)
		detail = self.application.handle(
			"GET",
			"/api/v1/validation-rule-sets/aov-main/2026.07.27.1",
			{},
		)

		self.assertEqual(200, history.status)
		self.assertEqual(1, history.body["total"])
		self.assertEqual(2, history.body["items"][0]["mapping_count"])
		self.assertEqual(2, history.body["items"][0]["whitelist_count"])
		self.assertEqual(1, history.body["items"][0]["content_check_count"])
		self.assertEqual(200, detail.status)
		self.assertEqual("aov-main", detail.body["rule_set"]["rule_set_id"])

	def test_newest_published_timestamp_is_listed_first(self) -> None:
		first = sample_rule_set()
		second = sample_rule_set()
		second["version"] = "2026.07.28.1"
		second["published_at"] = "2026-07-28T01:00:00Z"
		self.publish(first)
		self.publish(second)

		history = self.application.handle("GET", "/api/v1/validation-rule-sets", {})

		self.assertEqual(
			["2026.07.28.1", "2026.07.27.1"],
			[item["version"] for item in history.body["items"]],
		)

	def test_invalid_history_query_and_detail_return_client_errors(self) -> None:
		bad_query = self.application.handle(
			"GET",
			"/api/v1/validation-rule-sets?limit=0",
			{},
		)
		missing = self.application.handle(
			"GET",
			"/api/v1/validation-rule-sets/aov-main/missing",
			{},
		)

		self.assertEqual(400, bad_query.status)
		self.assertEqual(404, missing.status)

	def test_loopback_detection_supports_ipv4_ipv6_and_rejects_remote(self) -> None:
		self.assertTrue(_is_loopback_address("127.0.0.1"))
		self.assertTrue(_is_loopback_address("::1"))
		self.assertTrue(_is_loopback_address("localhost"))
		self.assertFalse(_is_loopback_address("192.168.1.20"))


if __name__ == "__main__":
	unittest.main()
