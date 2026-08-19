from __future__ import annotations

import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from AOVAutoPackerCurrent import AOVAutoPackerCurrentApp
from local_settings import load_local_settings, save_local_settings


class RegionalFtpProfileTests(unittest.TestCase):
	def test_region_profiles_round_trip_with_shared_credentials(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			settings_path = Path(temp_dir) / "settings.json"
			profiles = {
				"TW": {
					"host": "ftp-tw.example.test",
					"port": "21",
					"username": "tw-publisher",
					"password": "tw-shared-password",
					"remote_directory": "/release/TW",
					"passive": True,
				},
				"TH": {
					"host": "ftp-th.example.test",
					"port": "2121",
					"username": "th-publisher",
					"password": "th-shared-password",
					"remote_directory": "/release/TH",
					"passive": False,
				},
			}
			save_local_settings({"ftp_profiles": profiles}, settings_path)

			loaded = load_local_settings(settings_path)
			self.assertEqual(loaded["ftp_profiles"], profiles)
			document = json.loads(settings_path.read_text(encoding="utf-8"))
			self.assertEqual(document["settings"]["ftp_profiles"]["TW"]["password"], "tw-shared-password")

	def test_switching_region_loads_profile_and_checks_connection(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			settings_path = Path(temp_dir) / "settings.json"
			save_local_settings(
				{
					"package_region": "TW",
					"ftp_profiles": {
						"TW": {
							"host": "ftp-tw.example.test",
							"port": "21",
							"username": "tw-user",
							"password": "tw-password",
							"remote_directory": "/TW",
							"passive": True,
						},
						"TH": {
							"host": "ftp-th.example.test",
							"port": "2121",
							"username": "th-user",
							"password": "th-password",
							"remote_directory": "/TH",
							"passive": False,
						},
					},
				},
				settings_path,
			)
			with patch.dict("os.environ", {"AOV_AUTOPACKER_SETTINGS": str(settings_path)}):
				with patch("manual_publication_gui.FtpPublisher.check_connection") as check:
					root = tk.Tk()
					root.withdraw()
					self.addCleanup(lambda: root.destroy() if root.winfo_exists() else None)
					app = AOVAutoPackerCurrentApp(root)
					self.assertEqual(app.var_ftp_host.get(), "ftp-tw.example.test")
					self.assertEqual(app.var_ftp_password.get(), "tw-password")

					app.var_package_region.set("TH")
					root.update()
					self.assertEqual(app.var_ftp_host.get(), "ftp-th.example.test")
					self.assertEqual(app.var_ftp_port.get(), "2121")
					self.assertEqual(app.var_ftp_password.get(), "th-password")
					self.assertFalse(app.var_ftp_passive.get())
					self.assertTrue(check.called)


if __name__ == "__main__":
	unittest.main()
