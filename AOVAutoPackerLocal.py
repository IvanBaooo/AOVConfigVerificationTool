import os
import sys
import tkinter as tk
from tkinter import ttk

from AOVAutoPackerMVPCommit import resource_path
from AOVAutoPackerMVPCommitV10 import AOVAutoPackerMVPCommitV10App


APP_ID = "AOVAutoPacker.Local"


class AOVAutoPackerLocalApp(AOVAutoPackerMVPCommitV10App):
	def __init__(self, root: tk.Tk) -> None:
		super().__init__(root)
		self.root.title("AOVAutoPacker Local - ServerBytes Region Pack")


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

	AOVAutoPackerLocalApp(root)
	root.minsize(980, 1020)
	root.mainloop()


if __name__ == "__main__":
	main()
