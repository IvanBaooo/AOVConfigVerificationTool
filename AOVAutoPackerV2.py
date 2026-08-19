import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

from packer_core import PackagingError, pack_incremental_package


def resource_path(*relative_parts: str) -> str:
	base_path = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))
	return os.path.join(base_path, *relative_parts)


def get_output_parent() -> str:
	if getattr(sys, "frozen", False):
		return os.path.join(os.path.abspath(os.path.dirname(sys.executable)), "output")
	return os.path.join(os.path.abspath(os.path.dirname(__file__)), "output")


class AOVAutoPackerV2App:
	def __init__(self, root: tk.Tk) -> None:
		self.root = root
		self.root.title("AOVAutoPacker 2.0 MVP")

		self.main_frame = ttk.Frame(self.root, padding=12)
		self.main_frame.grid(row=0, column=0, sticky="nsew")
		self.root.rowconfigure(0, weight=1)
		self.root.columnconfigure(0, weight=1)
		self.main_frame.columnconfigure(0, weight=1)

		lbl_svn_list = ttk.Label(self.main_frame, text="SVN文件列表：")
		lbl_svn_list.grid(row=0, column=0, sticky="w", pady=(0, 4))

		svn_text_container = ttk.Frame(self.main_frame)
		svn_text_container.grid(row=1, column=0, sticky="nsew")
		self.main_frame.rowconfigure(1, weight=2)
		svn_text_container.rowconfigure(0, weight=1)
		svn_text_container.columnconfigure(0, weight=1)

		self.txt_svn_files = tk.Text(svn_text_container, height=10, wrap="none")
		self.txt_svn_files.grid(row=0, column=0, sticky="nsew")
		svn_scroll_y = ttk.Scrollbar(svn_text_container, orient="vertical", command=self.txt_svn_files.yview)
		svn_scroll_y.grid(row=0, column=1, sticky="ns")
		self.txt_svn_files.configure(yscrollcommand=svn_scroll_y.set)

		path_row = ttk.Frame(self.main_frame)
		path_row.grid(row=2, column=0, sticky="ew", pady=(8, 0))
		path_row.columnconfigure(1, weight=1)

		lbl_local_root = ttk.Label(path_row, text="本地文件根目录(ServerBytes)：")
		lbl_local_root.grid(row=0, column=0, sticky="w", padx=(0, 8))

		self.var_local_root = tk.StringVar()
		ent_local_root = ttk.Entry(path_row, textvariable=self.var_local_root)
		ent_local_root.grid(row=0, column=1, sticky="ew")

		btn_row = ttk.Frame(self.main_frame)
		btn_row.grid(row=3, column=0, sticky="ew", pady=(12, 0))
		btn_row.columnconfigure(0, weight=1)

		btn_start = ttk.Button(btn_row, text="开始打包", command=self.on_start_packaging)
		btn_start.grid(row=0, column=0, sticky="e")

		lbl_log = ttk.Label(self.main_frame, text="程序日志：")
		lbl_log.grid(row=4, column=0, sticky="w", pady=(12, 4))

		log_container = ttk.Frame(self.main_frame)
		log_container.grid(row=5, column=0, sticky="nsew")
		self.main_frame.rowconfigure(5, weight=3)
		log_container.rowconfigure(0, weight=1)
		log_container.columnconfigure(0, weight=1)

		self.txt_log = tk.Text(log_container, height=10, wrap="none", state="disabled")
		self.txt_log.grid(row=0, column=0, sticky="nsew")
		log_scroll_y = ttk.Scrollbar(log_container, orient="vertical", command=self.txt_log.yview)
		log_scroll_y.grid(row=0, column=1, sticky="ns")
		self.txt_log.configure(yscrollcommand=log_scroll_y.set)

		self.root.bind("<Control-Return>", lambda _e: self.on_start_packaging())
		self.append_log("应用已启动。V2 会额外生成 report.json，删除项会记录为跳过。", "info")

	def on_start_packaging(self) -> None:
		svn_file_list_text = self.txt_svn_files.get("1.0", "end").strip("\n")
		local_root = self.var_local_root.get().strip()

		try:
			result = pack_incremental_package(
				svn_text=svn_file_list_text,
				local_root=local_root,
				output_parent=get_output_parent(),
				log=self.append_log,
			)
		except PackagingError as e:
			self.append_log(f"[错误] {e}", "error")
			return
		except Exception as e:
			self.append_log(f"[致命错误] 打包过程失败：{e}", "error")
			return

		self.append_log("打包完成！", "success")
		self.append_log(
			f"成功文件数：{result.success_count}，失败文件数：{result.failure_count}，跳过文件数：{result.skipped_count}",
			"success",
		)
		self.append_log(f"压缩包：{result.tar_path}", "success")
		self.append_log(f"清单文件：{result.list_path}", "success")
		self.append_log(f"MD5文件：{result.md5_path}", "success")
		self.append_log(f"报告文件：{result.report_path}", "success")
		self.append_log_plain(f"包名：{os.path.basename(result.tar_path)}", level="success", bold=True)
		self.append_log_plain(f"包MD5：{result.md5}", level="success", bold=True)

		try:
			if sys.platform.startswith("win"):
				os.startfile(result.output_dir)
			elif sys.platform == "darwin":
				subprocess.run(["open", result.output_dir], check=False)
			else:
				subprocess.run(["xdg-open", result.output_dir], check=False)
			self.append_log("已自动打开输出文件夹", "success")
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

			ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AOVAutoPacker.2.0")
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

	AOVAutoPackerV2App(root)
	root.minsize(720, 520)
	root.mainloop()


if __name__ == "__main__":
	main()
