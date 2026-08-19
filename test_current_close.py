from __future__ import annotations

import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from AOVAutoPackerCurrent import AOVAutoPackerCurrentApp


class CurrentCloseTests(unittest.TestCase):
	def _create_app(self, settings_path: Path) -> tuple[tk.Tk, AOVAutoPackerCurrentApp]:
		with patch.dict(os.environ, {"AOV_AUTOPACKER_SETTINGS": str(settings_path)}):
			root = tk.Tk()
			root.withdraw()
			app = AOVAutoPackerCurrentApp(root)
		self.addCleanup(self._destroy_root, root)
		return root, app

	@staticmethod
	def _destroy_root(root: tk.Tk) -> None:
		try:
			root.destroy()
		except tk.TclError:
			pass

	def test_declining_close_after_save_failure_keeps_window_open(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root, app = self._create_app(Path(temp_dir) / "settings.json")
			with (
				patch.object(app, "save_current_settings", return_value=False),
				patch("AOVAutoPackerCurrent.messagebox.askyesno", return_value=False),
				patch.object(root, "destroy") as destroy,
			):
				app.on_close()
				destroy.assert_not_called()

	def test_confirming_close_after_save_failure_destroys_window(self) -> None:
		with tempfile.TemporaryDirectory() as temp_dir:
			root, app = self._create_app(Path(temp_dir) / "settings.json")
			with (
				patch.object(app, "save_current_settings", return_value=False),
				patch("AOVAutoPackerCurrent.messagebox.askyesno", return_value=True),
				patch.object(root, "destroy") as destroy,
			):
				app.on_close()
				destroy.assert_called_once_with()


if __name__ == "__main__":
	unittest.main()
