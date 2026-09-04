from __future__ import annotations

import unittest

from backend_archive_contract_v1 import ArchiveContractError, build_archive_record
from test_backend_archive_contract_v1_review_boundaries import report_with_skin_id


class BackendArchiveContractV1PrefixedDriveTests(unittest.TestCase):
	def test_rejects_double_slash_drive_path_attached_to_prefix(self) -> None:
		with self.assertRaisesRegex(ArchiveContractError, "Local absolute path"):
			build_archive_record(report_with_skin_id("prefixC://secret/file.xml"))

	def test_allows_http_url_embedded_in_text(self) -> None:
		value = "source=https://example.invalid/skin"
		payload = build_archive_record(report_with_skin_id(value))
		self.assertEqual(payload["validation"]["skin_precheck"]["items"][0]["id"], value)


if __name__ == "__main__":
	unittest.main()
