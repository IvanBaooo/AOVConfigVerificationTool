import os
import sys
import tkinter as tk
from tkinter import ttk

from AOVAutoPackerMVPCommit import resource_path
from AOVAutoPackerMVPCommitV4 import AOVAutoPackerMVPCommitV4App
from project_defaults import (
	DEFAULT_REGION_CODE,
	DEFAULT_SCOPE_ROOTS,
	LOCAL_SERVERBYTES_ROOT,
	LOCAL_SVN_EXE,
	LOCAL_TDR_ROOT,
	SERVERBYTES_SVN_URL,
	existing_path_or_empty,
)


class AOVAutoPackerMVPCommitV5App(AOVAutoPackerMVPCommitV4App):
	def __init__(self, root: tk.Tk) -> None:
		super().__init__(root)
		self.root.title("AOVAutoPacker MVP - B54 默认配置")
		self.apply_project_defaults()

	def apply_project_defaults(self) -> None:
		local_serverbytes = existing_path_or_empty(LOCAL_SERVERBYTES_ROOT)
		local_tdr = existing_path_or_empty(LOCAL_TDR_ROOT)
		local_svn_exe = existing_path_or_empty(LOCAL_SVN_EXE)

		if local_serverbytes and not self.var_local_root.get().strip():
			self.var_local_root.set(local_serverbytes)
		if local_tdr and not self.var_tdr_root.get().strip():
			self.var_tdr_root.set(local_tdr)
		if local_svn_exe and self.var_svn_exe.get().strip() == "svn":
			self.var_svn_exe.set(local_svn_exe)

		self.var_svn_target.set(SERVERBYTES_SVN_URL)
		self.var_region.set(DEFAULT_REGION_CODE)
		self.var_scope_roots.set(DEFAULT_SCOPE_ROOTS)
		self.var_use_auth_cache.set(True)
		self.append_log("已加载 B54 默认配置：SVN 目标使用 ServerBytes URL，本地目录使用当前机器 G 盘路径。", "info")


def main() -> None:
	if sys.platform.startswith("win"):
		try:
			import ctypes  # type: ignore

			ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AOVAutoPacker.MVPCommitV5")
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

	AOVAutoPackerMVPCommitV5App(root)
	root.minsize(980, 860)
	root.mainloop()


if __name__ == "__main__":
	main()
