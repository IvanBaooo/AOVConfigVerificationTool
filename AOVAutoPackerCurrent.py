from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from AOVAutoPackerLocalConfigured import AOVAutoPackerLocalConfiguredApp
from AOVAutoPackerMVPCommit import resource_path
from manual_publication_gui import ManualPublicationGuiMixin
from regional_ftp_profiles import RegionalFtpProfileGuiMixin
from release_baseline_gui import ReleaseBaselineGuiMixin
from validation_rule_gui import ValidationRuleGuiMixin


APP_ID = "AOVAutoPacker.Current"


class AOVAutoPackerCurrentApp(ReleaseBaselineGuiMixin, ValidationRuleGuiMixin, RegionalFtpProfileGuiMixin, ManualPublicationGuiMixin, AOVAutoPackerLocalConfiguredApp):
	def __init__(self, root: tk.Tk) -> None:
		super().__init__(root)
		self.root.title("AOVAutoPacker")
		self.root.protocol("WM_DELETE_WINDOW", self.on_close)

	def on_close(self) -> None:
		if not self.publication_close_allowed():
			return
		if self.save_current_settings(show_success=False):
			self.root.destroy()
			return

		close_anyway = messagebox.askyesno(
			"Settings not saved",
			"Local settings could not be saved. Close anyway?",
			parent=self.root,
		)
		if close_anyway:
			self.root.destroy()


def main() -> None:
	if sys.platform.startswith("win"):
		try:
			import ctypes  # type: ignore

			ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
		except Exception:
			pass

	root = tk.Tk()
	try:
		icon_path = resource_path("icon.ico")
		if os.path.exists(icon_path):
			root.iconbitmap(default=icon_path)
	except Exception:
		pass

	try:
		style = ttk.Style()
		if "vista" in style.theme_names():
			style.theme_use("vista")
		elif "clam" in style.theme_names():
			style.theme_use("clam")
	except Exception:
		pass

	AOVAutoPackerCurrentApp(root)
	root.minsize(900, 700)
	root.mainloop()


if __name__ == "__main__":
	main()
