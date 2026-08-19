import os
import sys
import tkinter as tk
from tkinter import ttk

from AOVAutoPackerMVPCommit import AOVAutoPackerMVPCommitApp, resource_path
from packer_core import PackagingError
from svn_commit_pack_input import build_packer_file_list_from_svn_log
from svn_commit_validation import RevisionSpecError


class AOVAutoPackerMVPCommitV2App(AOVAutoPackerMVPCommitApp):
	def build_packaging_text(self) -> str:
		raw_input = self.txt_package_input.get("1.0", "end").strip("\n")
		if self.var_input_method.get() != "revision_spec":
			return raw_input

		current_spec = self.var_current_revision_spec.get().strip()
		if not current_spec:
			raise PackagingError("选择 revision 输入方式时必须填写本次 revision。示例：r10001-r10005 或 r10001,r10003")
		if not raw_input.strip():
			raise PackagingError("选择 revision 输入方式时需要粘贴 svn log -v 内容，用于生成本次打包文件列表。")
		try:
			return build_packer_file_list_from_svn_log(raw_input, current_spec)
		except RevisionSpecError as err:
			raise PackagingError(str(err))


def main() -> None:
	if sys.platform.startswith("win"):
		try:
			import ctypes  # type: ignore

			ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AOVAutoPacker.MVPCommitV2")
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

	AOVAutoPackerMVPCommitV2App(root)
	root.minsize(920, 760)
	root.mainloop()


if __name__ == "__main__":
	main()
