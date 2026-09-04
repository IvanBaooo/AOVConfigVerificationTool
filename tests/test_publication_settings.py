from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from local_settings import load_local_settings, save_local_settings


class PublicationSettingsTests(unittest.TestCase):
	def test_publication_endpoints_persist_but_credentials_do_not(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			settings_path = Path(temp_dir) / "settings.json"
			save_local_settings(
				{
					"ftp_host": "ftp.example.test",
					"ftp_port": "21",
					"ftp_username": "publisher",
					"ftp_remote_directory": "/release/TW",
					"ftp_passive": True,
					"backend_url": "http://127.0.0.1:8780",
					"ftp_password": "do-not-save",
					"backend_token": "do-not-save",
				},
				settings_path,
			)

			loaded = load_local_settings(settings_path)
			document = json.loads(settings_path.read_text(encoding="utf-8"))
			self.assertEqual(loaded["ftp_host"], "ftp.example.test")
			self.assertEqual(loaded["ftp_remote_directory"], "/release/TW")
			self.assertTrue(loaded["ftp_passive"])
			self.assertEqual(loaded["backend_url"], "http://127.0.0.1:8780")
			self.assertNotIn("ftp_password", document["settings"])
			self.assertNotIn("backend_token", document["settings"])


if __name__ == "__main__":
	unittest.main()
