from __future__ import annotations

import copy
import unittest

from archive_backend.schema_validation import ArchivePayloadError, ArchivePayloadValidator
from backend_archive_contract_v1 import build_archive_record
from test_backend_archive_contract_v1 import final_sample_report


class ArchivePayloadCountValidationTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		cls.validator = ArchivePayloadValidator()

	def payload(self) -> dict[str, object]:
		return build_archive_record(final_sample_report())

	def test_rejects_package_count_that_does_not_match_files(self) -> None:
		payload = self.payload()
		payload["package"]["file_count"] = 999

		with self.assertRaisesRegex(ArchivePayloadError, "count mismatch"):
			self.validator.validate(payload)

	def test_rejects_unknown_file_status(self) -> None:
		payload = self.payload()
		payload["files"][0]["status"] = "copied"

		with self.assertRaisesRegex(ArchivePayloadError, "Unsupported file status"):
			self.validator.validate(payload)

	def test_accepts_supported_failed_and_skipped_counts(self) -> None:
		payload = self.payload()
		failed = copy.deepcopy(payload["files"][0])
		failed["fixed_path"] = "/Taiwan/failed.xml"
		failed["archive_path"] = "/sgame/gamedata/Taiwan/failed.xml"
		failed["status"] = "missing"
		skipped = copy.deepcopy(payload["files"][0])
		skipped["fixed_path"] = "/Taiwan/deleted.xml"
		skipped["archive_path"] = "/sgame/gamedata/Taiwan/deleted.xml"
		skipped["status"] = "deleted_skipped"
		payload["files"].extend([failed, skipped])
		payload["package"]["failed_count"] = 1
		payload["package"]["skipped_count"] = 1

		self.validator.validate(payload)


if __name__ == "__main__":
	unittest.main()
