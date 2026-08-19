from __future__ import annotations

import json
import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from AOVAutoPackerLocalConfigured import AOVAutoPackerLocalConfiguredApp


class ConfiguredGuiSettingsTests(unittest.TestCase):
	def test_gui_restores_machine_settings_but_not_task_input_or_password(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			settings_path = Path(temp_dir) / "settings.json"
			with patch.dict(os.environ, {"AOV_AUTOPACKER_SETTINGS": str(settings_path)}):
				root = tk.Tk()
				root.withdraw()
				app = AOVAutoPackerLocalConfiguredApp(root)
				app.var_local_root.set(r"G:\Custom\ServerBytes")
				app.var_package_region.set("TH")
				app.var_current_revision_spec.set("r1699997")
				app.var_svn_password.set("must-not-be-written")
				app.txt_commit_whitelist.insert("1.0", "/Thailand/ignore*.txt")
				self.assertTrue(app.save_current_settings(show_success=False))
				root.destroy()

				document = json.loads(settings_path.read_text(encoding="utf-8"))
				self.assertNotIn("svn_password", document["settings"])
				self.assertNotIn("current_revision_spec", document["settings"])

				root = tk.Tk()
				root.withdraw()
				restored_app = AOVAutoPackerLocalConfiguredApp(root)
				self.assertEqual(restored_app.var_local_root.get(), r"G:\Custom\ServerBytes")
				self.assertEqual(restored_app.var_package_region.get(), "TH")
				self.assertEqual(restored_app.var_current_revision_spec.get(), "")
				self.assertEqual(restored_app.var_svn_password.get(), "")
				self.assertEqual(
					restored_app.txt_commit_whitelist.get("1.0", "end-1c"),
					"/Thailand/ignore*.txt",
				)
				root.destroy()


if __name__ == "__main__":
	unittest.main()
