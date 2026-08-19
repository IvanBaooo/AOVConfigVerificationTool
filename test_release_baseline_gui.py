from __future__ import annotations

import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from AOVAutoPackerCurrent import AOVAutoPackerCurrentApp
from release_baseline_client import ReleaseBaseline


class ReleaseBaselineGuiTests(unittest.TestCase):
	def create_app(self, settings_path: Path):
		patcher = patch.dict(os.environ, {"AOV_AUTOPACKER_SETTINGS": str(settings_path)})
		patcher.start()
		self.addCleanup(patcher.stop)
		root = tk.Tk()
		root.withdraw()
		self.addCleanup(lambda: root.destroy() if root.winfo_exists() else None)
		return AOVAutoPackerCurrentApp(root)

	def baseline(self) -> ReleaseBaseline:
		return ReleaseBaseline(
			region_code="TW",
			package_id="sgame_TW_Beta54_20260714120000",
			release_time="2026-07-14T04:01:00Z",
			package_created_at="2026-07-14T12:00:00+08:00",
			released_revision_spec="r1700001,r1700003",
			released_revisions=(1700001, 1700003),
			last_checked_revision=1700003,
			package_version="Beta54",
		)

	def test_valid_remote_baseline_populates_existing_commit_inputs(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			app = self.create_app(Path(temp_dir) / "settings.json")
			app._baseline_request_generation = 3
			app._apply_release_baseline(3, self.baseline(), "http://127.0.0.1:8780", False)

			self.assertEqual(app.var_last_external_revision_spec.get(), "r1700001,r1700003")
			self.assertEqual(app.var_last_external_time.get(), "2026-07-14T04:01:00Z")
			self.assertIn("网页后端", app.var_release_baseline_source.get())
			self.assertIn("已连接", app.var_backend_connection_status.get())
			self.assertIn("sgame_TW", app.var_release_baseline_status.get())

	def test_failed_or_stale_request_preserves_manual_baseline(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			app = self.create_app(Path(temp_dir) / "settings.json")
			app.var_last_external_revision_spec.set("r1699997")
			app.var_last_external_time.set("manual-time")
			app._baseline_request_generation = 4
			app._apply_release_baseline_error(4, "TW", "offline")
			app._apply_release_baseline(3, self.baseline(), "http://127.0.0.1:8780", False)

			self.assertEqual(app.var_last_external_revision_spec.get(), "r1699997")
			self.assertEqual(app.var_last_external_time.get(), "manual-time")
			self.assertIn("手工输入", app.var_release_baseline_source.get())
			self.assertIn("连接失败", app.var_backend_connection_status.get())


if __name__ == "__main__":
	unittest.main()