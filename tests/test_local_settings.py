from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_settings import (
	LocalSettingsError,
	default_settings_path,
	load_local_settings,
	save_local_settings,
)


class LocalSettingsTests(unittest.TestCase):
	def test_round_trip_only_keeps_supported_machine_settings(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			settings_path = Path(temp_dir) / "settings.json"
			save_local_settings(
				{
					"local_root": r"G:\Branches\B54\Tools\TdrTable\ServerBytes",
					"package_region": "TW",
					"enable_commit_check": True,
					"commit_whitelist": "/Taiwan/Databin/Server/Actor/Hero_MD5*.txt",
					"svn_password": "must-not-be-written",
					"current_revision_spec": "r1699997",
					"unknown_field": "ignored",
				},
				settings_path,
			)

			document = json.loads(settings_path.read_text(encoding="utf-8"))
			self.assertEqual(document["schema_version"], 1)
			self.assertNotIn("svn_password", document["settings"])
			self.assertNotIn("current_revision_spec", document["settings"])
			self.assertNotIn("unknown_field", document["settings"])

			loaded = load_local_settings(settings_path)
			self.assertEqual(loaded["package_region"], "TW")
			self.assertTrue(loaded["enable_commit_check"])
			self.assertEqual(
				loaded["commit_whitelist"],
				"/Taiwan/Databin/Server/Actor/Hero_MD5*.txt",
			)

	def test_missing_settings_file_returns_empty_settings(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			settings_path = Path(temp_dir) / "missing.json"
			self.assertEqual(load_local_settings(settings_path), {})

	def test_invalid_settings_document_raises_clear_error(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			settings_path = Path(temp_dir) / "settings.json"
			settings_path.write_text("{invalid json", encoding="utf-8")

			with self.assertRaises(LocalSettingsError):
				load_local_settings(settings_path)

	def test_wrong_field_types_are_ignored(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			settings_path = Path(temp_dir) / "settings.json"
			settings_path.write_text(
				json.dumps(
					{
						"schema_version": 1,
						"settings": {
							"package_region": False,
							"enable_commit_check": "yes",
							"local_root": r"G:\ServerBytes",
						},
					}
				),
				encoding="utf-8",
			)

			self.assertEqual(
				load_local_settings(settings_path),
				{"local_root": r"G:\ServerBytes"},
			)

	def test_default_settings_live_next_to_project_entry(self) -> None:
		with patch.dict(os.environ, {}, clear=True):
			self.assertEqual(
				default_settings_path(),
				Path(__file__).resolve().parent.parent / "settings.json",
			)
	def test_environment_override_controls_default_path(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			settings_path = str(Path(temp_dir) / "custom.json")
			with patch.dict(os.environ, {"AOV_AUTOPACKER_SETTINGS": settings_path}):
				self.assertEqual(default_settings_path(), Path(settings_path))


if __name__ == "__main__":
	unittest.main()
