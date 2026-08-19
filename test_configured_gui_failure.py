from __future__ import annotations

import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from AOVAutoPackerLocalCompact import AOVAutoPackerLocalCompactApp
from AOVAutoPackerLocalConfigured import AOVAutoPackerLocalConfiguredApp


class ConfiguredGuiFailureTests(unittest.TestCase):
	def test_settings_save_failure_does_not_block_packaging(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			blocking_parent = Path(temp_dir) / "not-a-directory"
			blocking_parent.write_text("file", encoding="utf-8")

			root = tk.Tk()
			root.withdraw()
			app = AOVAutoPackerLocalConfiguredApp(root)
			app.settings_path = blocking_parent / "settings.json"

			with patch.object(AOVAutoPackerLocalCompactApp, "on_start_packaging") as pack:
				app.on_start_packaging()
				pack.assert_called_once_with()

			root.destroy()


if __name__ == "__main__":
	unittest.main()
