from __future__ import annotations

import unittest

from backend_archive_contract_v1 import ArchiveContractError, build_archive_record
from test_backend_archive_contract_v1 import final_sample_report


class BackendArchiveContractV1Rfc3339Tests(unittest.TestCase):
	def test_builder_rejects_iso_week_date_not_allowed_by_schema(self) -> None:
		report = final_sample_report()
		report["created_at"] = "2026-W29-1T15:35:24+08:00"
		with self.assertRaisesRegex(ArchiveContractError, "RFC 3339"):
			build_archive_record(report)

	def test_builder_accepts_normal_rfc3339_timestamp(self) -> None:
		payload = build_archive_record(final_sample_report())
		self.assertEqual(payload["created_at"], "2026-07-13T15:35:24+08:00")


if __name__ == "__main__":
	unittest.main()
