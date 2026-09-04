from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from packer_core import PackResult
from packer_mvp_optimized import apply_optimized_validation_to_report


class PackerChangeSetReportTests(unittest.TestCase):
	def test_changeset_is_written_to_existing_report_without_affecting_validation_status(self) -> None:
		validation = {
			"summary": {"error_count": 0, "warning_count": 0, "confirm_count": 0, "skipped_count": 0},
			"checks": {},
		}
		change_set = {
			"schema_version": "aov-dtxml-changeset/v1",
			"status": "warning",
			"summary": {"file_count": 1, "sheet_count": 1, "change_count": 2, "error_count": 1},
			"changes": [{"sheet": "svr下发皮肤上下架表"}],
			"errors": [{"message": "one file could not be read"}],
		}
		with tempfile.TemporaryDirectory() as temporary_directory:
			report_path = Path(temporary_directory) / "report.json"
			result = PackResult(
				base_name="sgame_TW_Beta54_20260101000000",
				output_dir=temporary_directory,
				tar_path=str(Path(temporary_directory) / "package.tar.gz"),
				list_path=str(Path(temporary_directory) / "package.list.txt"),
				md5_path=str(Path(temporary_directory) / "package.md5.txt"),
				report_path=str(report_path),
				md5="md5",
				sha256="sha256",
				success_count=1,
				failure_count=0,
				skipped_count=0,
				report={"status": {"validation_status": "not_started"}},
			)
			with (
				patch("packer_mvp_optimized.run_full_mvp_validations_optimized", return_value=validation),
				patch("packer_mvp_optimized.run_dtxml_changeset", return_value=change_set),
			):
				apply_optimized_validation_to_report(
					result=result,
					local_root="G:/TdrTable/ServerBytes",
					svn_text="M ServerBytes/Taiwan/file.xml",
					validation_config={"dtxml_diff": {"enabled": True}},
				)

			stored = json.loads(report_path.read_text(encoding="utf-8"))
		self.assertEqual(change_set, stored["change_set"])
		self.assertEqual("passed", stored["status"]["validation_status"])


if __name__ == "__main__":
	unittest.main()
