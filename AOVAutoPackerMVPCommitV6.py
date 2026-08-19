import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

from AOVAutoPackerMVPCommit import resource_path
from AOVAutoPackerMVPCommitV5 import AOVAutoPackerMVPCommitV5App
from packer_core import PackagingError
from packer_mvp_optimized import pack_incremental_package_mvp_optimized


class AOVAutoPackerMVPCommitV6App(AOVAutoPackerMVPCommitV5App):
	def __init__(self, root: tk.Tk) -> None:
		super().__init__(root)
		self.root.title("AOVAutoPacker MVP - B54 优化校验")
		self._insert_whitelist_frame()

	def _insert_whitelist_frame(self) -> None:
		for widget in self.main_frame.grid_slaves():
			row = int(widget.grid_info().get("row", 0))
			if row >= 8:
				widget.grid_configure(row=row + 1)

		whitelist_frame = ttk.LabelFrame(self.main_frame, text="提交校验白名单", padding=8)
		whitelist_frame.grid(row=8, column=0, sticky="ew", pady=(10, 0))
		whitelist_frame.columnconfigure(0, weight=1)

		ttk.Label(
			whitelist_frame,
			text="每行一个路径或通配符。示例：/Taiwan/Databin/Server/Actor/Hero_MD5*.txt 或 Hero_MD5*.txt",
		).grid(row=0, column=0, sticky="w")

		self.txt_commit_whitelist = tk.Text(whitelist_frame, height=4, wrap="none")
		self.txt_commit_whitelist.grid(row=1, column=0, sticky="ew", pady=(6, 0))

	def _read_whitelist_paths(self):
		if not hasattr(self, "txt_commit_whitelist"):
			return []
		raw_text = self.txt_commit_whitelist.get("1.0", "end").strip()
		paths = []
		for line in raw_text.replace("；", "\n").replace("，", "\n").replace(",", "\n").splitlines():
			value = line.strip()
			if value:
				paths.append(value)
		return paths

	def build_validation_config(self, raw_input_text: str):
		config = super().build_validation_config(raw_input_text)
		if not config:
			return config
		commit_record = config.get("commit_record")
		if isinstance(commit_record, dict):
			commit_record["whitelist_paths"] = self._read_whitelist_paths()
		return config

	def on_start_packaging(self) -> None:
		raw_input_text = self.txt_package_input.get("1.0", "end").strip("\n")
		local_root = self.var_local_root.get().strip()
		self._resolved_svn_log_text = ""

		try:
			svn_file_list_text = self.build_packaging_text()
			result = pack_incremental_package_mvp_optimized(
				svn_text=svn_file_list_text,
				local_root=local_root,
				output_parent=self.get_output_parent(),
				validation_config=self.build_validation_config(raw_input_text),
				log=self.append_log,
			)
		except PackagingError as e:
			self.append_log(f"[错误] {e}", "error")
			return
		except Exception as e:
			self.append_log(f"[致命错误] 打包过程失败：{e}", "error")
			return

		self.append_log("打包完成。", "success")
		self.append_log(
			f"成功文件数：{result.success_count}，失败文件数：{result.failure_count}，跳过文件数：{result.skipped_count}",
			"success",
		)
		self.append_log(f"压缩包：{result.tar_path}", "success")
		self.append_log(f"清单文件：{result.list_path}", "success")
		self.append_log(f"MD5 文件：{result.md5_path}", "success")
		self.append_log(f"报告文件：{result.report_path}", "success")

		validation_summary = result.report.get("validation", {}).get("summary", {})
		self.append_log(
			"校验汇总："
			f"error={validation_summary.get('error_count', 0)}，"
			f"warning={validation_summary.get('warning_count', 0)}，"
			f"confirm={validation_summary.get('confirm_count', 0)}",
			"success",
		)
		self.append_log_plain(f"包名：{os.path.basename(result.tar_path)}", level="success", bold=True)
		self.append_log_plain(f"包 MD5：{result.md5}", level="success", bold=True)

		try:
			if sys.platform.startswith("win"):
				os.startfile(result.output_dir)
			elif sys.platform == "darwin":
				subprocess.run(["open", result.output_dir], check=False)
			else:
				subprocess.run(["xdg-open", result.output_dir], check=False)
			self.append_log("已自动打开输出文件夹。", "success")
		except Exception as open_err:
			self.append_log(f"自动打开文件夹失败：{open_err}", "warning")


def main() -> None:
	if sys.platform.startswith("win"):
		try:
			import ctypes  # type: ignore

			ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AOVAutoPacker.MVPCommitV6")
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

	AOVAutoPackerMVPCommitV6App(root)
	root.minsize(980, 900)
	root.mainloop()


if __name__ == "__main__":
	main()
