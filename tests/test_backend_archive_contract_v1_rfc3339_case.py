from __future__ import annotations

import unittest

from backend_archive_contract_v1 import ArchiveContractError, build_archive_record
from test_backend_archive_contract_v1 import final_sample_report
import test_backend_archive_contract_v1_jsonschema as jsonschema_tests


class BackendArchiveContractV1Rfc3339CaseTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		jsonschema_tests.BackendArchiveContractV1JsonSchemaTests.setUpClass()
		cls.validator = jsonschema_tests.BackendArchiveContractV1JsonSchemaTests.validator

	def test_lowercase_t_and_z_are_rejected_by_builder_and_final_schema(self) -> None:
		report = final_sample_report()
		report["created_at"] = "2026-07-13t15:35:24z"
		with self.assertRaises(ArchiveContractError):
			build_archive_record(report)

		payload = build_archive_record(final_sample_report())
		payload["created_at"] = "2026-07-13t15:35:24z"
		self.assertTrue(any(error.validator == "pattern" for error in self.validator.iter_errors(payload)))


if __name__ == "__main__":
	unittest.main()
