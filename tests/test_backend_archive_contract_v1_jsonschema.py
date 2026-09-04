from __future__ import annotations

import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from backend_archive_contract_v1 import build_archive_record
from test_backend_archive_contract_v1 import final_sample_report


class BackendArchiveContractV1JsonSchemaTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		schema_dir = Path(__file__).parent.parent / "schemas"
		cls.final_schema = json.loads(
			(schema_dir / "aov-package-archive-v1-final.schema.json").read_text(encoding="utf-8")
		)
		strict_schema = json.loads(
			(schema_dir / "aov-package-archive-v1-strict.schema.json").read_text(encoding="utf-8")
		)

		Draft202012Validator.check_schema(strict_schema)
		Draft202012Validator.check_schema(cls.final_schema)
		registry = Registry().with_resource(
			strict_schema["$id"],
			Resource.from_contents(strict_schema),
		)
		cls.validator = Draft202012Validator(
			cls.final_schema,
			registry=registry,
			format_checker=Draft202012Validator.FORMAT_CHECKER,
		)

	def test_real_builder_payload_passes_full_final_schema(self) -> None:
		payload = build_archive_record(final_sample_report())
		errors = sorted(self.validator.iter_errors(payload), key=lambda error: list(error.path))
		self.assertEqual(errors, [], "\n".join(error.message for error in errors))

	def test_payload_with_acknowledgments_passes_full_final_schema(self) -> None:
		report = final_sample_report()
		report["validation"]["acknowledgments"] = [
			{
				"type": "skin_precheck",
				"name": "皮肤促销窗口预检",
				"acknowledged_at": "2026-09-04T10:00:00+08:00",
			}
		]
		payload = build_archive_record(report)
		errors = sorted(self.validator.iter_errors(payload), key=lambda error: list(error.path))
		self.assertEqual(errors, [], "\n".join(error.message for error in errors))

	def test_final_schema_rejects_mutable_status_and_bad_archive_root(self) -> None:
		payload = build_archive_record(final_sample_report())
		payload["status"]["ftp_status"] = "success"
		payload["package"]["archive_root"] = "/sgame/../secret"

		errors = list(self.validator.iter_errors(payload))
		self.assertGreaterEqual(len(errors), 2)


if __name__ == "__main__":
	unittest.main()
