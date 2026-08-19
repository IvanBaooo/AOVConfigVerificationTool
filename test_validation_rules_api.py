from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from archive_backend.api import ArchiveApplication
from archive_backend.repository import ArchiveRepository
from archive_backend.schema_validation import ArchivePayloadValidator
from test_validation_rule_sets import sample_rule_set


class ValidationRulesApiTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		self.application = ArchiveApplication(
			repository=ArchiveRepository(Path(self.temp_dir.name) / "archives.sqlite3"),
			validator=ArchivePayloadValidator(),
			access_token="rules-token",
		)
		self.headers = {
			"Authorization": "Bearer rules-token",
			"Content-Type": "application/json",
		}

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def publish(self, payload: dict[str, object]):
		return self.application.handle(
			"POST",
			"/api/v1/validation-rule-sets",
			self.headers,
			json.dumps(payload, ensure_ascii=False).encode("utf-8"),
		)

	def test_publish_replay_and_fetch_region_effective_rules(self) -> None:
		created = self.publish(sample_rule_set())
		replayed = self.publish(sample_rule_set())
		latest = self.application.handle(
			"GET",
			"/api/v1/validation-rules/latest?region_code=TW",
			{"Authorization": "Bearer rules-token"},
		)

		self.assertEqual(201, created.status)
		self.assertEqual("created", created.body["result"])
		self.assertEqual(200, replayed.status)
		self.assertEqual("true", replayed.headers["Idempotency-Replayed"])
		self.assertEqual(200, latest.status)
		effective = latest.body["rule_set"]
		self.assertEqual("TW", effective["region_code"])
		self.assertEqual("TW 活动表", effective["rules"]["path_mappings"][0]["table_name"])

	def test_same_version_with_different_content_conflicts(self) -> None:
		self.publish(sample_rule_set())
		changed = copy.deepcopy(sample_rule_set())
		changed["notes"] = "different"

		response = self.publish(changed)

		self.assertEqual(409, response.status)
		self.assertEqual("rule_version_conflict", response.body["error"]["code"])

	def test_latest_requires_region_and_published_rules(self) -> None:
		missing_region = self.application.handle(
			"GET",
			"/api/v1/validation-rules/latest",
			{"Authorization": "Bearer rules-token"},
		)
		not_published = self.application.handle(
			"GET",
			"/api/v1/validation-rules/latest?region_code=TH",
			{"Authorization": "Bearer rules-token"},
		)

		self.assertEqual(400, missing_region.status)
		self.assertEqual(404, not_published.status)


if __name__ == "__main__":
	unittest.main()
