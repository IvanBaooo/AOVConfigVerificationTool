from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from manual_publication import (
	ArchiveSyncResult,
	BackendSettings,
	FtpSettings,
	FtpUploadResult,
	ManualPublicationService,
	RemoteFilePolicy,
)
from test_backend_archive_contract_v1 import final_sample_report


class ManualPublicationStageTests(unittest.TestCase):
	def test_stage_callback_exposes_ftp_and_backend_boundary(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root = Path(temp_dir)
			archive_path = root / "sgame_TW_Beta54_20260713153524.tar.gz"
			archive_path.write_bytes(b"archive")
			report = final_sample_report()
			report["package"]["name"] = archive_path.name
			report["package"]["md5"] = hashlib.md5(archive_path.read_bytes()).hexdigest()
			report["package"]["sha256"] = hashlib.sha256(archive_path.read_bytes()).hexdigest()
			report_path = root / "package.report.json"
			report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

			class StubFtp:
				def upload(self, *_args, **_kwargs):
					return FtpUploadResult("uploaded", archive_path.name, "/release", 7)

			class StubBackend:
				def sync_report(self, *_args, **_kwargs):
					return ArchiveSyncResult("created", "package-id")

			stages = []
			service = ManualPublicationService(
				ftp_publisher=StubFtp(),
				backend_client=StubBackend(),
			)
			service.publish(
				archive_path=archive_path,
				report_path=report_path,
				ftp_settings=FtpSettings("ftp.example.test"),
				backend_settings=BackendSettings("http://127.0.0.1:8780", "token"),
				policy=RemoteFilePolicy.REQUIRE_ABSENT,
				stage=stages.append,
			)

			self.assertEqual(
				stages,
				["preflight", "ftp_upload", "backend_archive", "complete"],
			)


if __name__ == "__main__":
	unittest.main()
