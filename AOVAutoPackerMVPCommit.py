import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

from packer_core import PackagingError
from packer_mvp_full import pack_incremental_package_mvp_full
from svn_commit_validation import RevisionSpecError, build_file_list_from_svn_log


def resource_path(*relative_parts: str) -> str:
	base_path = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))
	return os.path.join(base_path, *relative_parts)


def get_output_parent() -> str:
	if getattr(sys, "frozen", False):
		return os.path.join(os.path.abspath(os.path.dirname(sys.executable)), "output")
	return os.path.join(os.path.abspath(os.path.dirname(__file__)), "output")


class AOVAutoPackerMVPCommitApp:
	def __init__(self, root: tk.Tk) -> None:
		self.root = root
		self.last_pack_result = None
		self.root.title("AOVAutoPacker MVP - 本地校验")

		self.main_frame = ttk.Frame(self.root, padding=12)
		self.main_frame.grid(row=0, column=0, sticky="nsew")
		self.root.rowconfigure(0, weight=1)
		self.root.columnconfigure(0, weight=1)
		self.main_frame.columnconfigure(0, weight=1)

		input_mode_frame = ttk.LabelFrame(self.main_frame, text="打包范围输入方式", padding=8)
		input_mode_frame.grid(row=0, column=0, sticky="ew")
		self.var_input_method = tk.StringVar(value="pasted_svn_file_list")
		ttk.Radiobutton(
			input_mode_frame,
			text="粘贴指定 SVN 文件列表（手动指定打包内容）",
			variable=self.var_input_method,
			value="pasted_svn_file_list",
			command=self.refresh_input_labels,
		).grid(row=0, column=0, sticky="w")
		ttk.Radiobutton(
			input_mode_frame,
			text="输入 SVN revision，并粘贴 svn log -v 内容（由工具生成文件列表）",
			variable=self.var_input_method,
			value="revision_spec",
			command=self.refresh_input_labels,
		).grid(row=1, column=0, sticky="w", pady=(4, 0))

		self.lbl_package_input = ttk.Label(self.main_frame, text="")
		self.lbl_package_input.grid(row=1, column=0, sticky="w", pady=(10, 4))

		input_container = ttk.Frame(self.main_frame)
		input_container.grid(row=2, column=0, sticky="nsew")
		self.main_frame.rowconfigure(2, weight=2)
		input_container.rowconfigure(0, weight=1)
		input_container.columnconfigure(0, weight=1)

		self.txt_package_input = tk.Text(input_container, height=10, wrap="none")
		self.txt_package_input.grid(row=0, column=0, sticky="nsew")
		input_scroll_y = ttk.Scrollbar(input_container, orient="vertical", command=self.txt_package_input.yview)
		input_scroll_y.grid(row=0, column=1, sticky="ns")
		self.txt_package_input.configure(yscrollcommand=input_scroll_y.set)

		path_row = ttk.Frame(self.main_frame)
		path_row.grid(row=3, column=0, sticky="ew", pady=(8, 0))
		path_row.columnconfigure(1, weight=1)
		ttk.Label(path_row, text="本地文件根目录（ServerBytes）：").grid(row=0, column=0, sticky="w", padx=(0, 8))
		self.var_local_root = tk.StringVar()
		ttk.Entry(path_row, textvariable=self.var_local_root).grid(row=0, column=1, sticky="ew")

		revision_frame = ttk.LabelFrame(self.main_frame, text="本地提交记录校验", padding=8)
		revision_frame.grid(row=4, column=0, sticky="ew", pady=(10, 0))
		revision_frame.columnconfigure(1, weight=1)
		revision_frame.columnconfigure(3, weight=1)

		self.var_enable_commit_check = tk.BooleanVar(value=True)
		ttk.Checkbutton(revision_frame, text="启用两次对外之间的 SVN 改动检查", variable=self.var_enable_commit_check).grid(
			row=0, column=0, sticky="w", columnspan=4
		)

		ttk.Label(revision_frame, text="本次 revision：").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
		self.var_current_revision_spec = tk.StringVar()
		ttk.Entry(revision_frame, textvariable=self.var_current_revision_spec).grid(row=1, column=1, sticky="ew", pady=(6, 0))

		ttk.Label(revision_frame, text="上次对外 revision：").grid(row=1, column=2, sticky="w", padx=(12, 8), pady=(6, 0))
		self.var_last_external_revision_spec = tk.StringVar()
		ttk.Entry(revision_frame, textvariable=self.var_last_external_revision_spec).grid(row=1, column=3, sticky="ew", pady=(6, 0))

		ttk.Label(revision_frame, text="上次对外时间：").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
		self.var_last_external_time = tk.StringVar()
		ttk.Entry(revision_frame, textvariable=self.var_last_external_time).grid(row=2, column=1, sticky="ew", pady=(6, 0))

		ttk.Label(revision_frame, text="范围目录：").grid(row=2, column=2, sticky="w", padx=(12, 8), pady=(6, 0))
		self.var_scope_roots = tk.StringVar(value="/Taiwan")
		ttk.Entry(revision_frame, textvariable=self.var_scope_roots).grid(row=2, column=3, sticky="ew", pady=(6, 0))

		skin_frame = ttk.LabelFrame(self.main_frame, text="更新内容校验 MVP", padding=8)
		skin_frame.grid(row=5, column=0, sticky="ew", pady=(10, 0))
		skin_frame.columnconfigure(1, weight=1)
		skin_frame.columnconfigure(3, weight=1)

		self.var_enable_skin_validation = tk.BooleanVar(value=False)
		ttk.Checkbutton(skin_frame, text="启用皮肤预埋检查", variable=self.var_enable_skin_validation).grid(
			row=0, column=0, sticky="w", columnspan=4
		)

		ttk.Label(skin_frame, text="TdrTable 根目录：").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
		self.var_tdr_root = tk.StringVar()
		ttk.Entry(skin_frame, textvariable=self.var_tdr_root).grid(row=1, column=1, columnspan=3, sticky="ew", pady=(6, 0))

		ttk.Label(skin_frame, text="地区：").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
		self.var_region = tk.StringVar(value="TW")
		ttk.Entry(skin_frame, textvariable=self.var_region, width=8).grid(row=2, column=1, sticky="w", pady=(6, 0))

		ttk.Label(skin_frame, text="开始时间：").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
		self.var_window_start = tk.StringVar()
		ttk.Entry(skin_frame, textvariable=self.var_window_start).grid(row=3, column=1, sticky="ew", pady=(6, 0))

		ttk.Label(skin_frame, text="结束时间：").grid(row=3, column=2, sticky="w", padx=(12, 8), pady=(6, 0))
		self.var_window_end = tk.StringVar()
		ttk.Entry(skin_frame, textvariable=self.var_window_end).grid(row=3, column=3, sticky="ew", pady=(6, 0))

		btn_row = ttk.Frame(self.main_frame)
		btn_row.grid(row=6, column=0, sticky="ew", pady=(12, 0))
		btn_row.columnconfigure(0, weight=1)
		ttk.Button(btn_row, text="开始打包", command=self.on_start_packaging).grid(row=0, column=0, sticky="e")

		lbl_log = ttk.Label(self.main_frame, text="程序日志：")
		lbl_log.grid(row=7, column=0, sticky="w", pady=(12, 4))

		log_container = ttk.Frame(self.main_frame)
		log_container.grid(row=8, column=0, sticky="nsew")
		self.main_frame.rowconfigure(8, weight=3)
		log_container.rowconfigure(0, weight=1)
		log_container.columnconfigure(0, weight=1)

		self.txt_log = tk.Text(log_container, height=10, wrap="none", state="disabled")
		self.txt_log.grid(row=0, column=0, sticky="nsew")
		log_scroll_y = ttk.Scrollbar(log_container, orient="vertical", command=self.txt_log.yview)
		log_scroll_y.grid(row=0, column=1, sticky="ns")
		self.txt_log.configure(yscrollcommand=log_scroll_y.set)

		self.root.bind("<Control-Return>", lambda _e: self.on_start_packaging())
		self.refresh_input_labels()
		self.append_log("应用已启动。当前入口支持本地提交记录校验与皮肤预埋 MVP 校验。", "info")

	def refresh_input_labels(self) -> None:
		if self.var_input_method.get() == "revision_spec":
			self.lbl_package_input.configure(text="SVN log -v 内容（会按“本次 revision”生成打包文件列表）：")
		else:
			self.lbl_package_input.configure(text="SVN 文件列表（粘贴指定文件列表，报告会标注为手动范围）：")

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
			return build_file_list_from_svn_log(raw_input, current_spec)
		except RevisionSpecError as err:
			raise PackagingError(str(err))

	def build_validation_config(self, raw_input_text: str):
		config = {}

		if self.var_enable_skin_validation.get():
			start = self.var_window_start.get().strip()
			end = self.var_window_end.get().strip()
			if not start or not end:
				raise PackagingError("启用皮肤预埋检查时必须填写检查窗口开始/结束时间。格式示例：20260710000000")
			config["check_window"] = {
				"start_time": start,
				"end_time": end,
				"source": "local_mvp_ui",
			}
			config["region_code"] = self.var_region.get().strip() or "TW"
			tdr_root = self.var_tdr_root.get().strip()
			if tdr_root:
				config["tdr_root"] = tdr_root

		if self.var_enable_commit_check.get():
			scope_roots = [
				item.strip()
				for item in self.var_scope_roots.get().replace("；", ";").replace("，", ",").replace(";", ",").split(",")
				if item.strip()
			]
			commit_record = {
				"enabled": True,
				"input_method": self.var_input_method.get(),
				"current_revision_spec": self.var_current_revision_spec.get().strip(),
				"last_external_revision_spec": self.var_last_external_revision_spec.get().strip(),
				"last_external_time": self.var_last_external_time.get().strip(),
				"scope_roots": scope_roots,
			}
			if self.var_input_method.get() == "revision_spec":
				commit_record["svn_log_text"] = raw_input_text
			config["commit_record"] = commit_record

		return config or None

	def on_start_packaging(self) -> None:
		self.last_pack_result = None
		raw_input_text = self.txt_package_input.get("1.0", "end").strip("\n")
		local_root = self.var_local_root.get().strip()

		try:
			svn_file_list_text = self.build_packaging_text()
			result = pack_incremental_package_mvp_full(
				svn_text=svn_file_list_text,
				local_root=local_root,
				output_parent=get_output_parent(),
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

	def append_log(self, message: str, level: str = "info") -> None:
		self.txt_log.configure(state="normal")
		tag_name = f"log_{level}"
		self.txt_log.insert("end", message + "\n", tag_name)
		color = {
			"success": "green",
			"error": "red",
			"warning": "orange",
			"info": "black",
		}.get(level, "black")
		self.txt_log.tag_config(tag_name, foreground=color)
		self.txt_log.see("end")
		self.txt_log.configure(state="disabled")

	def append_log_plain(self, message: str, level: str = "info", bold: bool = False) -> None:
		self.txt_log.configure(state="normal")
		tag_name = f"log_plain_{level}_{'bold' if bold else 'normal'}"
		color = {
			"success": "green",
			"error": "red",
			"warning": "orange",
			"info": "black",
		}.get(level, "black")
		try:
			self.txt_log.tag_config(tag_name, foreground=color, font=("TkDefaultFont", 9, "bold" if bold else "normal"))
		except Exception:
			self.txt_log.tag_config(tag_name, foreground=color)
		self.txt_log.insert("end", message + "\n", tag_name)
		self.txt_log.see("end")
		self.txt_log.configure(state="disabled")


def main() -> None:
	if sys.platform.startswith("win"):
		try:
			import ctypes  # type: ignore

			ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AOVAutoPacker.MVPCommit")
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

	AOVAutoPackerMVPCommitApp(root)
	root.minsize(920, 760)
	root.mainloop()


if __name__ == "__main__":
	main()
