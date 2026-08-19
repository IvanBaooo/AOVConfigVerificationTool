import os
import sys
import tkinter as tk
from tkinter import ttk

from AOVAutoPackerMVPCommit import resource_path
from AOVAutoPackerMVPCommitV8 import AOVAutoPackerMVPCommitV8App
from package_region_target import scope_root_for_region
from project_defaults import SERVERBYTES_SVN_URL


class AOVAutoPackerMVPCommitV10App(AOVAutoPackerMVPCommitV8App):
	def __init__(self, root: tk.Tk) -> None:
		super().__init__(root)
		self.root.title("AOVAutoPacker MVP - ServerBytes 锚点区域打包")
		self._insert_serverbytes_anchor_frame()
		self.apply_serverbytes_anchor_defaults()
		self.var_package_region.trace_add("write", lambda *_args: self.sync_region_scope())

	def _insert_serverbytes_anchor_frame(self) -> None:
		for widget in self.main_frame.grid_slaves():
			row = int(widget.grid_info().get("row", 0))
			if row >= 11:
				widget.grid_configure(row=row + 1)

		anchor_frame = ttk.LabelFrame(self.main_frame, text="SVN 锚点策略", padding=8)
		anchor_frame.grid(row=11, column=0, sticky="ew", pady=(10, 0))
		anchor_frame.columnconfigure(0, weight=1)
		ttk.Label(
			anchor_frame,
			text="SVN 目标固定为 ServerBytes 根目录；实际打包内容由“本次 revision + 打包区域”共同确定。",
		).grid(row=0, column=0, sticky="w")
		ttk.Button(anchor_frame, text="恢复 ServerBytes 根锚点", command=self.apply_serverbytes_anchor_defaults).grid(
			row=1, column=0, sticky="w", pady=(6, 0)
		)

	def apply_serverbytes_anchor_defaults(self) -> None:
		self.var_svn_target.set(SERVERBYTES_SVN_URL)
		self.sync_region_scope()

	def sync_region_scope(self) -> None:
		region_code = self.var_package_region.get().strip() or self.var_region.get().strip() or "TW"
		scope_root = scope_root_for_region(region_code)
		if scope_root:
			self.var_scope_roots.set(scope_root)
		self.var_region.set(region_code.upper())
		self.var_enable_region_filter.set(True)


def main() -> None:
	if sys.platform.startswith("win"):
		try:
			import ctypes  # type: ignore

			ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AOVAutoPacker.MVPCommitV10")
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

	AOVAutoPackerMVPCommitV10App(root)
	root.minsize(980, 1020)
	root.mainloop()


if __name__ == "__main__":
	main()
