import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

from AOVAutoPackerMVPCommit import resource_path
from AOVAutoPackerMVPCommitV7 import AOVAutoPackerMVPCommitV7App
from package_region_target import scope_root_for_region, svn_target_for_region
from packer_core import PackagingError
from packer_mvp_region_name_only import pack_incremental_package_mvp_region_name_only


class AOVAutoPackerMVPCommitV9App(AOVAutoPackerMVPCommitV7App):
	def __init__(self, root: tk.Tk) -> None:
		super().__init__(root)
		self.root.title("AOVAutoPacker MVP - 区域仅用于命名")
		self._insert_region_target_frame()
		self.apply_region_target_defaults()

	def _insert_region_target_frame(self) -> None:
		for widget in self.main_frame.grid_slaves():
			row = int(widget.grid_info().get("row", 0))
			if row >= 10:
				widget.grid_configure(row=row + 1)

		target_frame = ttk.LabelFrame(self.main_frame, text="区域与 SVN 目录", padding=8)
		target_frame.grid(row=10, column=0, sticky="ew", pady=(10, 0))
		target_frame.columnconfigure(0, weight=1)
		ttk.Label(
			target_frame,
			text="区域只用于包名；实际打包内容以本次 revision 在 SVN 目标目录下返回的提交文件为准。",
		).grid(row=0, column=0, sticky="w")
		ttk.Button(target_frame, text="按打包区域刷新 SVN 目标目录", command=self.apply_region_target_defaults).grid(
			row=1, column=0, sticky="w", pady=(6, 0)
		)

	def apply_region_target_defaults(self) -> None:
		region_code = self.var_package_region.get().strip() if hasattr(self, "var_package_region") else "TW"
		target = svn_target_for_region(region_code)
		scope_root = scope_root_for_region(region_code)
		if target:
			self.var_svn_target.set(target)
		if scope_root:
			self.var_scope_roots.set(scope_root)

	def build_validation_config(self, raw_input_text: str):
		config = super().build_validation_config(raw_input_text)
		if not config:
			config = {}
		config["package_region_usage"] = "name_only"
		config["package_content_source"] = "revision_and_svn_target"
		config["package_region_filter_enabled"] = False
		commit_record = config.get("commit_record")
		if isinstance(commit_record, dict):
			commit_record["package_region_usage"] = "name_only"
			commit_record["package_content_source"] = "revision_and_svn_target"
			commit_record["package_region_filter_enabled"] = False
		return config

	def on_start_packaging(self) -> None:
		raw_input_text = self.txt_package_input.get("1.0", "end").strip("\n")
		local_root = self.var_local_root.get().strip()
		self._resolved_svn_log_text = ""

		try:
			svn_file_list_text = self.build_packaging_text()
			result = pack_incremental_package_mvp_region_name_only(
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

			ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AOVAutoPacker.MVPCommitV9")
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

	AOVAutoPackerMVPCommitV9App(root)
	root.minsize(980, 980)
	root.mainloop()


if __name__ == "__main__":
	main()
