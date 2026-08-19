from __future__ import annotations

import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from AOVAutoPackerCurrent import AOVAutoPackerCurrentApp


class CurrentPublicationGuiTests(unittest.TestCase):
	def create_app(self, settings_path: Path):
		patcher = patch.dict(os.environ, {"AOV_AUTOPACKER_SETTINGS": str(settings_path)})
		patcher.start()
		self.addCleanup(patcher.stop)
		root = tk.Tk()
		root.withdraw()
		self.addCleanup(lambda: root.destroy() if root.winfo_exists() else None)
		return root, AOVAutoPackerCurrentApp(root)

	def test_publication_tab_and_credentials_are_session_only(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			_root, app = self.create_app(Path(temp_dir) / "settings.json")
			tabs = [app.notebook.tab(tab, "text") for tab in app.notebook.tabs()]
			self.assertEqual(tabs, ["Daily", "Config", "归档配置"])
			self.assertEqual(str(app.btn_confirm_archive.cget("state")), "disabled")
			self.assertEqual(app.var_backend_url.get(), "http://127.0.0.1:8780")
			app.var_ftp_password.set("ftp-secret")
			app.var_backend_token.set("backend-secret")
			settings = app.collect_local_settings()
			self.assertNotIn("ftp_password", settings)
			self.assertNotIn("backend_token", settings)

	def test_successful_packaging_is_forwarded_to_manual_archive_panel(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root_path = Path(temp_dir)
			_root, app = self.create_app(root_path / "settings.json")
			result = SimpleNamespace(
				tar_path=str(root_path / "sgame_TW_Beta54_test.tar.gz"),
				list_path=str(root_path / "package.list.txt"),
				md5_path=str(root_path / "package.md5.txt"),
				report_path=str(root_path / "package.report.json"),
				output_dir=str(root_path),
				md5="a" * 32,
				report={
					"status": {"package_status": "success", "validation_status": "warning"},
					"validation": {"summary": {"error_count": 0, "warning_count": 1}},
					"input": {"region_filter": {"enabled": True, "included_count": 2, "excluded_count": 0}},
				},
				failure_count=0,
				success_count=2,
				skipped_count=0,
			)
			app.build_packaging_text = lambda: "M ServerBytes/Taiwan/test.xml"
			app.build_validation_config = lambda _raw: {}
			with patch("AOVAutoPackerMVPCommitV8.pack_incremental_package_mvp_region_named", return_value=result), patch(
				"AOVAutoPackerMVPCommitV8.os.startfile", create=True
			):
				app.on_start_packaging()

			self.assertIs(app.last_pack_result, result)
			self.assertEqual(app.var_publication_status.get(), "Report 待人工确认")
			self.assertEqual(str(app.btn_confirm_archive.cget("state")), "normal")

	def test_successful_warning_report_enables_manual_archive(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root_path = Path(temp_dir)
			_root, app = self.create_app(root_path / "settings.json")
			result = SimpleNamespace(
				tar_path=str(root_path / "sgame_TW_Beta54_20260713153524.tar.gz"),
				report_path=str(root_path / "package.report.json"),
				report={"validation": {"summary": {"error_count": 0, "warning_count": 2}}},
				failure_count=0,
				success_count=20,
			)
			app._activate_pack_result(result)
			self.assertEqual(str(app.btn_open_report.cget("state")), "normal")
			self.assertEqual(str(app.btn_confirm_archive.cget("state")), "normal")
			self.assertEqual(app.var_publication_status.get(), "Report 待人工确认")

	def test_error_report_blocks_manual_archive(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root_path = Path(temp_dir)
			_root, app = self.create_app(root_path / "settings.json")
			result = SimpleNamespace(
				tar_path=str(root_path / "sgame_TW_Beta54_20260713153524.tar.gz"),
				report_path=str(root_path / "package.report.json"),
				report={"validation": {"summary": {"error_count": 1, "warning_count": 0}}},
				failure_count=0,
				success_count=20,
			)
			app._activate_pack_result(result)
			self.assertEqual(str(app.btn_confirm_archive.cget("state")), "disabled")
			self.assertEqual(app.var_publication_status.get(), "Report 存在错误，禁止归档")


if __name__ == "__main__":
	unittest.main()
