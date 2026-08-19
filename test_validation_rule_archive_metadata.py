from __future__ import annotations

import unittest

from backend_archive_contract_v1 import ArchiveContractError, build_archive_record
from backend_archive_payload import build_archive_payload
from test_backend_archive_contract_v1 import final_sample_report


class ValidationRuleArchiveMetadataTests(unittest.TestCase):
	def test_rule_version_and_hash_are_preserved_in_archive_payload(self) -> None:
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

		payload = build_archive_payload(report)
		final_payload = build_archive_record(report)
		self.assertEqual("2026.07.27.1", payload["validation"]["rule_set"]["version"])
		self.assertEqual("a" * 64, final_payload["validation"]["rule_set"]["rule_hash"])
		self.assertNotIn("message", payload["validation"]["rule_set"])

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
