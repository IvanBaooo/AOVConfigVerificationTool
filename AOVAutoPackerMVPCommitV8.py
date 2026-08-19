import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

from AOVAutoPackerMVPCommit import resource_path
from AOVAutoPackerMVPCommitV7 import AOVAutoPackerMVPCommitV7App
from packer_core import PackagingError
from packer_mvp_region_named import pack_incremental_package_mvp_region_named


class AOVAutoPackerMVPCommitV8App(AOVAutoPackerMVPCommitV7App):
	def __init__(self, root: tk.Tk) -> None:
		super().__init__(root)
		self.root.title("AOVAutoPacker MVP - 区域过滤")
		self._insert_region_filter_frame()

	def _insert_region_filter_frame(self) -> None:
		for widget in self.main_frame.grid_slaves():
			row = int(widget.grid_info().get("row", 0))
			if row >= 10:
				widget.grid_configure(row=row + 1)

		filter_frame = ttk.LabelFrame(self.main_frame, text="打包区域过滤", padding=8)
		filter_frame.grid(row=10, column=0, sticky="ew", pady=(10, 0))
		filter_frame.columnconfigure(0, weight=1)

		self.var_enable_region_filter = tk.BooleanVar(value=True)
		ttk.Checkbutton(
			filter_frame,
			text="打包前只保留当前打包区域的 ServerBytes 文件",
			variable=self.var_enable_region_filter,
		).grid(row=0, column=0, sticky="w")
		ttk.Label(
			filter_frame,
			text="例如打包区域为 TW 时，仅保留 ServerBytes/Taiwan/...；其他区域会记录到 report.input.region_filter。",
		).grid(row=1, column=0, sticky="w", pady=(6, 0))

	def build_validation_config(self, raw_input_text: str):
		config = super().build_validation_config(raw_input_text)
		if not config:
			config = {}
		config["package_region_filter_enabled"] = self.var_enable_region_filter.get()
		commit_record = config.get("commit_record")
		if isinstance(commit_record, dict):
			commit_record["package_region_filter_enabled"] = self.var_enable_region_filter.get()
		return config

	def on_start_packaging(self) -> None:
		self.last_pack_result = None
		raw_input_text = self.txt_package_input.get("1.0", "end").strip("\n")
		local_root = self.var_local_root.get().strip()
		self._resolved_svn_log_text = ""

		try:
			svn_file_list_text = self.build_packaging_text()
			result = pack_incremental_package_mvp_region_named(
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

		self.last_pack_result = result
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
		region_filter = result.report.get("input", {}).get("region_filter", {})
		if isinstance(region_filter, dict) and region_filter.get("enabled"):
			self.append_log(
				"区域过滤汇总："
				f"保留={region_filter.get('included_count', 0)}，"
				f"排除={region_filter.get('excluded_count', 0)}",
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

			ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AOVAutoPacker.MVPCommitV8")
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

	AOVAutoPackerMVPCommitV8App(root)
	root.minsize(980, 980)
	root.mainloop()


if __name__ == "__main__":
	main()
