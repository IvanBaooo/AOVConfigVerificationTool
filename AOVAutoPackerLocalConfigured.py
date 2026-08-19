from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import ttk

from AOVAutoPackerLocalCompact import AOVAutoPackerLocalCompactApp
from AOVAutoPackerMVPCommit import resource_path
from local_settings import (
	LocalSettingsError,
	default_settings_path,
	load_local_settings,
	save_local_settings,
)


APP_ID = "AOVAutoPacker.LocalConfigured"


class AOVAutoPackerLocalConfiguredApp(AOVAutoPackerLocalCompactApp):
	SETTING_VARIABLES = {
		"local_root": "var_local_root",
		"tdr_root": "var_tdr_root",
		"svn_target": "var_svn_target",
		"svn_exe": "var_svn_exe",
		"svn_username": "var_svn_username",
		"use_auth_cache": "var_use_auth_cache",
		"last_external_revision_spec": "var_last_external_revision_spec",
		"last_external_time": "var_last_external_time",
		"scope_roots": "var_scope_roots",
		"package_version": "var_package_version",
		"package_region": "var_package_region",
		"enable_commit_check": "var_enable_commit_check",
		"enable_region_filter": "var_enable_region_filter",
		"enable_skin_validation": "var_enable_skin_validation",
		"window_start": "var_window_start",
		"window_end": "var_window_end",
	}

	def __init__(self, root: tk.Tk) -> None:
		self.settings_path = default_settings_path()
		super().__init__(root)
		self.root.title("AOVAutoPacker Local")
		self.load_saved_settings()
		self.root.protocol("WM_DELETE_WINDOW", self.on_close)

	def _build_config_tab(self, parent: ttk.Frame) -> None:
		super()._build_config_tab(parent)
		action_row = ttk.Frame(parent)
		action_row.grid(row=5, column=0, sticky="ew", pady=(10, 0))
		action_row.columnconfigure(0, weight=1)
		tk.Button(action_row, text="Reload settings", command=self.load_saved_settings).grid(
			row=0, column=1, sticky="e"
		)
		tk.Button(action_row, text="Save settings", command=self.save_current_settings).grid(
			row=0, column=2, sticky="e", padx=(8, 0)
		)

	def collect_local_settings(self) -> dict[str, str | bool]:
		settings = {
			key: getattr(self, variable_name).get()
			for key, variable_name in self.SETTING_VARIABLES.items()
		}
		settings["commit_whitelist"] = self.txt_commit_whitelist.get("1.0", "end-1c")
		return settings

	def apply_local_settings(self, settings: dict[str, str | bool]) -> None:
		package_region = settings.get("package_region")
		if isinstance(package_region, str):
			self.var_package_region.set(package_region)

		for key, variable_name in self.SETTING_VARIABLES.items():
			if key == "package_region" or key not in settings:
				continue
			getattr(self, variable_name).set(settings[key])

		commit_whitelist = settings.get("commit_whitelist")
		if isinstance(commit_whitelist, str):
			self.txt_commit_whitelist.delete("1.0", "end")
			self.txt_commit_whitelist.insert("1.0", commit_whitelist)
		self.refresh_input_labels()

	def load_saved_settings(self) -> None:
		try:
			settings = load_local_settings(self.settings_path)
		except LocalSettingsError as error:
			self.append_log(f"[Settings warning] {error}", "warning")
			return

		if not settings:
			self.append_log("No saved local settings; project defaults are active.", "info")
			return
		self.apply_local_settings(settings)
		self.append_log(f"Local settings loaded: {self.settings_path}", "info")

	def save_current_settings(self, show_success: bool = True) -> bool:
		try:
			saved_path = save_local_settings(self.collect_local_settings(), self.settings_path)
		except LocalSettingsError as error:
			self.append_log(f"[Settings warning] {error}", "warning")
			return False
		if show_success:
			self.append_log(f"Local settings saved: {saved_path}", "success")
		return True

	def on_start_packaging(self) -> None:
		self.save_current_settings(show_success=False)
		super().on_start_packaging()

	def on_close(self) -> None:
		self.save_current_settings(show_success=False)
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

	AOVAutoPackerLocalConfiguredApp(root)
	root.minsize(900, 700)
	root.mainloop()


if __name__ == "__main__":
	main()
