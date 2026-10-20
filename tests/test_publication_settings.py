from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from electron_bridge import merge_settings, renderer_settings
from local_settings import load_local_settings, save_local_settings


class PublicationSettingsTests(unittest.TestCase):
	def test_publication_endpoints_and_backend_token_persist_but_passwords_do_not(self) -> None:
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
					"backend_token": "aov_pk_secret",
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
			self.assertEqual(document["settings"]["backend_token"], "aov_pk_secret")

	def test_backend_token_not_exposed_to_renderer(self) -> None:
		exposed = renderer_settings({"backend_url": "http://x", "backend_token": "aov_pk_secret"})
		self.assertNotIn("backend_token", exposed)
		self.assertTrue(exposed["backend_token_configured"])
		exposed_empty = renderer_settings({"backend_url": "http://x"})
		self.assertFalse(exposed_empty["backend_token_configured"])

	def test_merge_settings_keeps_token_when_incoming_blank(self) -> None:
		existing = {"backend_url": "http://x", "backend_token": "aov_pk_secret"}
		merged = merge_settings(existing, {"backend_url": "http://y", "backend_token": ""})
		self.assertEqual(merged["backend_token"], "aov_pk_secret")
		self.assertEqual(merged["backend_url"], "http://y")

		replaced = merge_settings(existing, {"backend_token": "aov_pk_new"})
		self.assertEqual(replaced["backend_token"], "aov_pk_new")

		cleared = merge_settings(existing, {"backend_token": "", "clear_backend_token": True})
		self.assertEqual(cleared["backend_token"], "")


if __name__ == "__main__":
	unittest.main()
