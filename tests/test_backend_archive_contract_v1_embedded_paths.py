from __future__ import annotations

import unittest

from backend_archive_contract_v1 import ArchiveContractError, build_archive_record
from archive_fixtures import check_entry
from test_backend_archive_contract_v1 import final_sample_report


class BackendArchiveContractV1EmbeddedPathTests(unittest.TestCase):
	def _report_with_skin_id(self, value: str) -> dict[str, object]:
		report = final_sample_report()
		report["validation"]["checks"]["skin_precheck"].update(
			{
				"status": "confirm",
				"item_count": 1,
				"items": [
					{
						"id": value,
						"long_term_status": {"ID": value},
						"promotions": [],
					}
				],
			}
		)
		return report

	def test_rejects_drive_path_even_when_attached_to_prefix(self) -> None:
		report = self._report_with_skin_id(r"prefixG:\Branches\secret\skin.dtxml")
		with self.assertRaisesRegex(ArchiveContractError, "Local absolute path"):
			build_archive_record(report)

	def test_does_not_treat_https_url_as_drive_path(self) -> None:
		payload = build_archive_record(self._report_with_skin_id("https://example.invalid/skin"))
		self.assertEqual(
			check_entry(payload, "skin_precheck")["items"][0]["id"],
			"https://example.invalid/skin",
		)


if __name__ == "__main__":
	unittest.main()
