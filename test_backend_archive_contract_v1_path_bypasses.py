from __future__ import annotations

import unittest

from backend_archive_contract_v1 import ArchiveContractError, build_archive_record
from test_backend_archive_contract_v1_review_boundaries import report_with_skin_id


class BackendArchiveContractV1PathBypassTests(unittest.TestCase):
	def test_rejects_forward_slash_drive_path(self) -> None:
		for value in ("C://secret/file.xml", "source=C://secret/file.xml"):
			with self.subTest(value=value):
				with self.assertRaisesRegex(ArchiveContractError, "Local absolute path"):
					build_archive_record(report_with_skin_id(value))

	def test_rejects_embedded_windows_root_path(self) -> None:
		with self.assertRaisesRegex(ArchiveContractError, "Local absolute path"):
			build_archive_record(report_with_skin_id(r"source=\Users\admin\secret.xml"))

	def test_https_url_still_passes(self) -> None:
		payload = build_archive_record(report_with_skin_id("https://example.invalid/skin"))
		self.assertEqual(
			payload["validation"]["skin_precheck"]["items"][0]["id"],
			"https://example.invalid/skin",
		)


if __name__ == "__main__":
	unittest.main()
