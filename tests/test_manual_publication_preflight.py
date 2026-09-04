from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from manual_publication import PublicationPreflightError, build_verified_archive_payload
from test_backend_archive_contract_v1 import final_sample_report


class ManualPublicationPreflightTests(unittest.TestCase):
	def test_modified_archive_is_rejected_after_report_review(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			archive_path = root / "sgame_TW_Beta54_20260713153524.tar.gz"
			archive_path.write_bytes(b"reviewed-archive")
			report = final_sample_report()
			report["package"]["name"] = archive_path.name
			report["package"]["md5"] = hashlib.md5(archive_path.read_bytes()).hexdigest()
			report["package"]["sha256"] = hashlib.sha256(archive_path.read_bytes()).hexdigest()
			report_path = root / "package.report.json"
			report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

			build_verified_archive_payload(report_path, archive_path)
			archive_path.write_bytes(b"changed-after-review")

			with self.assertRaises(PublicationPreflightError):
				build_verified_archive_payload(report_path, archive_path)


if __name__ == "__main__":
	unittest.main()
