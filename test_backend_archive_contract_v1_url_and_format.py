from __future__ import annotations

import unittest

from backend_archive_contract_v1 import ArchiveContractError, build_archive_record
from test_backend_archive_contract_v1 import final_sample_report
import test_backend_archive_contract_v1_jsonschema as jsonschema_tests
from test_backend_archive_contract_v1_review_boundaries import report_with_skin_id


class BackendArchiveContractV1UrlAndFormatTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		jsonschema_tests.BackendArchiveContractV1JsonSchemaTests.setUpClass()
		cls.validator = jsonschema_tests.BackendArchiveContractV1JsonSchemaTests.validator

	def test_url_does_not_hide_local_path_in_query(self) -> None:
		value = "https://example.invalid/?path=C://secret/file.xml"
		with self.assertRaisesRegex(ArchiveContractError, "Local absolute path"):
			build_archive_record(report_with_skin_id(value))

	def test_schema_format_checker_rejects_invalid_created_at(self) -> None:
		payload = build_archive_record(final_sample_report())
		payload["created_at"] = "not-a-date"

		errors = list(self.validator.iter_errors(payload))
		self.assertTrue(
			any(error.validator == "format" and error.validator_value == "date-time" for error in errors)
		)


if __name__ == "__main__":
	unittest.main()
