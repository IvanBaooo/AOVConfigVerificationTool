import tkinter as tk
from tkinter import ttk
import os
import sys
import tarfile
import hashlib
import subprocess
from datetime import datetime
from typing import List, Tuple


def resource_path(*relative_parts: str) -> str:
	"""获取资源文件的绝对路径，兼容 PyInstaller onefile (_MEIPASS)。"""
	base_path = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))
	return os.path.join(base_path, *relative_parts)


class IncrementalPackerApp:
	def __init__(self, root: tk.Tk) -> None:
		self.root = root
		self.root.title("AOVAutoPacker 1.0")

		# Top-level container
		self.main_frame = ttk.Frame(self.root, padding=12)
		self.main_frame.grid(row=0, column=0, sticky="nsew")

		# Configure resizing behavior
		self.root.rowconfigure(0, weight=1)
		self.root.columnconfigure(0, weight=1)
		self.main_frame.columnconfigure(0, weight=1)

		# SVN 文件列表标签
		lbl_svn_list = ttk.Label(self.main_frame, text="SVN文件列表：")
		lbl_svn_list.grid(row=0, column=0, sticky="w", pady=(0, 4))

		# SVN 文件列表文本框 + 滚动条
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

		# 本地文件根目录行
		row_idx = 2
		path_row = ttk.Frame(self.main_frame)
		path_row.grid(row=row_idx, column=0, sticky="ew", pady=(8, 0))
		path_row.columnconfigure(1, weight=1)

		lbl_local_root = ttk.Label(path_row, text="本地文件根目录(ServerBytes)：")
		lbl_local_root.grid(row=0, column=0, sticky="w", padx=(0, 8))

		self.var_local_root = tk.StringVar()
		ent_local_root = ttk.Entry(path_row, textvariable=self.var_local_root)
		ent_local_root.grid(row=0, column=1, sticky="ew")

		#（已按需求移除 输出父目录 输入框）

		# 开始打包按钮
		row_idx += 1
		btn_row = ttk.Frame(self.main_frame)
		btn_row.grid(row=row_idx, column=0, sticky="ew", pady=(12, 0))
		btn_row.columnconfigure(0, weight=1)

		btn_start = ttk.Button(btn_row, text="开始打包", command=self.on_start_packaging)
		btn_start.grid(row=0, column=0, sticky="e")

		# 程序日志标签
		row_idx += 1
		lbl_log = ttk.Label(self.main_frame, text="程序日志：")
		lbl_log.grid(row=row_idx, column=0, sticky="w", pady=(12, 4))

		# 日志文本框 + 滚动条
		row_idx += 1
		log_container = ttk.Frame(self.main_frame)
		log_container.grid(row=row_idx, column=0, sticky="nsew")
		self.main_frame.rowconfigure(row_idx, weight=3)
		log_container.rowconfigure(0, weight=1)
		log_container.columnconfigure(0, weight=1)

		self.txt_log = tk.Text(log_container, height=10, wrap="none", state="disabled")
		self.txt_log.grid(row=0, column=0, sticky="nsew")
		log_scroll_y = ttk.Scrollbar(log_container, orient="vertical", command=self.txt_log.yview)
		log_scroll_y.grid(row=0, column=1, sticky="ns")
		self.txt_log.configure(yscrollcommand=log_scroll_y.set)

		# 快捷键：Ctrl+Enter 开始打包
		self.root.bind("<Control-Return>", lambda _e: self.on_start_packaging())

		# 初始日志
		self.append_log("应用已启动。请粘贴 SVN 文件列表，填写目录后点击 '开始打包'。", "info")

	# ========== 空函数与UI辅助 ==========
	def on_start_packaging(self) -> None:
		"""开始打包的回调：完成路径转换、打包、生成列表与MD5，并输出日志。"""
		svn_file_list_text = self.get_svn_file_list()
		local_root = self.var_local_root.get().strip()
		# 输出目录固定为可执行文件同目录下的 output 文件夹
		# 兼容 exe 打包后的情况
		if getattr(sys, 'frozen', False):
			# 如果是 exe 打包后的环境
			exe_dir = os.path.abspath(os.path.dirname(sys.executable))
			output_parent = os.path.join(exe_dir, "output")
		else:
			# 如果是 Python 脚本环境
			script_dir = os.path.abspath(os.path.dirname(__file__))
			output_parent = os.path.join(script_dir, "output")

		# 基本校验
		if not svn_file_list_text.strip():
			self.append_log("[错误] SVN文件列表为空。", "error")
			return
		if not local_root:
			self.append_log("[错误] 本地文件根目录(ServerBytes) 未填写。", "error")
			return
		# 不再需要校验输出目录输入框

		self.append_log("正在分析文件列表...", "info")
		fixed_paths = self.parse_fixed_paths_from_svn_list(svn_file_list_text)
		if not fixed_paths:
			self.append_log("[错误] 未从 SVN 文件列表中解析到任何有效路径（未匹配到 ServerBytes 锚点）。", "error")
			return

		# 生成输出文件名与同名子目录
		timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
		base_name = f"sgame_{timestamp}"
		tar_filename = f"{base_name}.tar.gz"
		list_filename = f"{base_name}.list.txt"
		md5_filename = f"{base_name}.md5.txt"

		# 在输出路径下创建同名子目录
		output_dir = os.path.join(output_parent, base_name)
		os.makedirs(output_dir, exist_ok=True)
		tar_path = os.path.join(output_dir, tar_filename)
		list_path = os.path.join(output_dir, list_filename)
		md5_path = os.path.join(output_dir, md5_filename)

		self.append_log(f"输出目录：{output_dir}", "info")
		self.append_log(f"将生成：{tar_filename}、{list_filename}、{md5_filename}", "info")

		archive_root = "/sgame/gamedata"
		success_entries: List[Tuple[str, str]] = []  # (archive_path, local_path)
		failure_count = 0

		try:
			with tarfile.open(tar_path, mode="w:gz") as tar:
				for fixed_path in fixed_paths:
					# fixed_path 形如 "/Taiwan/.../file"
					local_path = self.build_local_path(local_root, fixed_path)
					archive_path = self.build_archive_path(archive_root, fixed_path)

					if not os.path.isfile(local_path):
						self.append_log(f"[跳过] 本地文件不存在：{local_path}", "warning")
						failure_count += 1
						continue

					try:
						self.append_log(f"正在打包：{archive_path} ...", "info")
						tar.add(local_path, arcname=archive_path)
						success_entries.append((archive_path, local_path))
					except Exception as add_err:
						failure_count += 1
						self.append_log(f"[错误] 添加到压缩包失败：{archive_path} -> {add_err}", "error")

			# 生成 .list 和 打包文件的 .md5（仅对最终包计算MD5）
			self.append_log("正在生成清单与MD5校验（仅最终压缩包）...", "info")
			try:
				# 写入清单（归档内路径列表）
				with open(list_path, "w", encoding="utf-8") as f_list:
					for archive_path, _local_path in success_entries:
						f_list.write(f"{archive_path}\n")
					# 结尾空一行并统计总行数
					f_list.write("\n")
					f_list.write(f"共{len(success_entries)}行\n")

				# 仅计算最终 tar.gz 包的 MD5
				pkg_md5 = self.compute_md5(tar_path)
				with open(md5_path, "w", encoding="utf-8") as f_md5:
					f_md5.write(f"{pkg_md5}  {os.path.basename(tar_path)}\n")
			except Exception as write_err:
				self.append_log(f"[错误] 写入清单或MD5失败：{write_err}", "error")

			self.append_log("打包完成！", "success")
			self.append_log(f"成功文件数：{len(success_entries)}，失败文件数：{failure_count}", "success")
			self.append_log(f"压缩包：{tar_path}", "success")
			self.append_log(f"清单文件：{list_path}", "success")
			self.append_log(f"MD5文件：{md5_path}", "success")
			# 最后两行（不带时间戳、加粗）：包名与MD5
			self.append_log_plain(f"包名：{os.path.basename(tar_path)}", level="success", bold=True)
			self.append_log_plain(f"包MD5：{pkg_md5}", level="success", bold=True)
			
			# 打包成功后自动打开输出文件夹
			try:
				if sys.platform.startswith('win'):
					os.startfile(output_dir)
				elif sys.platform == 'darwin':
					subprocess.run(['open', output_dir], check=False)
				else:
					subprocess.run(['xdg-open', output_dir], check=False)
				self.append_log("已自动打开输出文件夹", "success")
			except Exception as open_err:
				self.append_log(f"自动打开文件夹失败：{open_err}", "warning")
		except Exception as e:
			self.append_log(f"[致命错误] 打包过程失败：{e}", "error")

	def get_svn_file_list(self) -> str:
		return self.txt_svn_files.get("1.0", "end").strip("\n")

	def clear_logs(self) -> None:
		self.txt_log.configure(state="normal")
		self.txt_log.delete("1.0", "end")
		self.txt_log.configure(state="disabled")

	def append_log(self, message: str, level: str = "info") -> None:
		"""添加带颜色的日志消息
		
		Args:
			message: 日志消息
			level: 日志级别 ("info", "success", "warning", "error")
		"""
		self.txt_log.configure(state="normal")
		
		# 根据级别设置标签和颜色
		tag_name = f"log_{level}"
		
		# 带时间戳的消息
		timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
		decorated_message = f"[{timestamp}] {message}"
		
		# 插入消息
		self.txt_log.insert("end", decorated_message + "\n", tag_name)
		
		# 配置标签颜色
		if level == "success":
			self.txt_log.tag_config(tag_name, foreground="green")
		elif level == "error":
			self.txt_log.tag_config(tag_name, foreground="red")
		elif level == "warning":
			self.txt_log.tag_config(tag_name, foreground="orange")
		else:  # info
			self.txt_log.tag_config(tag_name, foreground="black")
		
		self.txt_log.see("end")
		self.txt_log.configure(state="disabled")

	def append_log_plain(self, message: str, level: str = "info", bold: bool = False) -> None:
		"""添加不带时间戳的日志，可选择加粗。"""
		self.txt_log.configure(state="normal")
		tag_name = f"log_plain_{level}_{'bold' if bold else 'normal'}"
		font_weight = "bold" if bold else "normal"
		# 插入消息（不带时间戳）
		self.txt_log.insert("end", message + "\n", tag_name)
		# 配色与加粗
		color = {
			"success": "green",
			"error": "red",
			"warning": "orange",
			"info": "black",
		}.get(level, "black")
		try:
			self.txt_log.tag_config(tag_name, foreground=color, font=("TkDefaultFont", 9, font_weight))
		except Exception:
			self.txt_log.tag_config(tag_name, foreground=color)
		self.txt_log.see("end")
		self.txt_log.configure(state="disabled")

	# ========== 业务辅助函数 ==========
	@staticmethod
	def parse_fixed_paths_from_svn_list(svn_text: str) -> List[str]:
		"""从 SVN 文本解析出以 ServerBytes 为锚点的固定路径（以 / 开头）。

		解析规则：
		- 每行文本查找 "ServerBytes" 的位置；
		- 取其之后的子路径，若没有以 '/' 开头则补一个；
		- 结果路径使用 '/' 分隔，形如 "/Taiwan/.../file"；
		- 忽略无法匹配到锚点的行。
		- 去重并保持原始顺序。
		"""
		results: List[str] = []
		seen = set()
		for raw_line in svn_text.splitlines():
			line = raw_line.strip()
			if not line:
				continue
			# 容错：去掉行首的更改标记，如 "M ", "A ", "D " 等
			if len(line) > 2 and line[1] == ' ' and line[0] in {'M', 'A', 'D', 'R'}:
				line = line[2:].strip()

			anchor_idx = line.find("ServerBytes")
			if anchor_idx == -1:
				continue

			after_anchor = line[anchor_idx + len("ServerBytes"):]
			# 归一化分隔符为 '/'（SVN 风格）
			after_anchor = after_anchor.replace("\\", "/")

			# 确保以 '/' 开头
			if not after_anchor.startswith("/"):
				after_anchor = "/" + after_anchor

			fixed_path = after_anchor

			# 防止尾随空白
			fixed_path = fixed_path.strip()
			# 去除多余的重复斜杠
			while '//' in fixed_path:
				fixed_path = fixed_path.replace('//', '/')

			if fixed_path and fixed_path not in seen:
				seen.add(fixed_path)
				results.append(fixed_path)

		return results

	@staticmethod
	def build_local_path(local_root: str, fixed_path: str) -> str:
		"""将固定路径映射为本地Windows路径：local_root + fixed_path（使用os.sep）。"""
		sub_parts = [p for p in fixed_path.strip('/').split('/') if p]
		return os.path.join(local_root, *sub_parts)

	@staticmethod
	def build_archive_path(archive_root: str, fixed_path: str) -> str:
		"""构建归档路径（始终使用'/'）：archive_root + fixed_path。"""
		# 确保 archive_root 不以 '/' 结尾
		arc_root = archive_root.rstrip('/')
		if fixed_path.startswith('/'):
			return f"{arc_root}{fixed_path}"
		return f"{arc_root}/{fixed_path}"

	@staticmethod
	def compute_md5(file_path: str, chunk_size: int = 1024 * 1024) -> str:
		md5 = hashlib.md5()
		with open(file_path, 'rb') as f:
			while True:
				data = f.read(chunk_size)
				if not data:
					break
				md5.update(data)
		return md5.hexdigest()


def main() -> None:
	# Windows 任务栏图标依赖 AppUserModelID，需在创建窗口前设置
	if sys.platform.startswith('win'):
		try:
			import ctypes  # type: ignore
			ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AOVAutoPacker.1.0")
		except Exception:
			pass

	root = tk.Tk()
	
	# 设置窗口图标（兼容打包环境）
	try:
		icon_path = resource_path('icon.ico')
		if os.path.exists(icon_path):
			# 使用 default 参数提高在某些 Windows 环境下的兼容性
			root.iconbitmap(default=icon_path)
			print(f"✅ 成功加载图标：{icon_path}")
		else:
			print(f"⚠️ 图标文件不存在：{icon_path}")
			# 如果没有图标文件，尝试使用默认图标
			root.iconbitmap(default="")
	except Exception as e:
		print(f"❌ 设置图标失败：{e}")
		pass  # 如果设置图标失败，继续运行
	
	# 使用系统主题外观
	try:
		style = ttk.Style()
		if "vista" in style.theme_names():
			style.theme_use("vista")
		elif "clam" in style.theme_names():
			style.theme_use("clam")
	except Exception:
		pass

	IncrementalPackerApp(root)
	root.minsize(720, 520)
	root.mainloop()


if __name__ == "__main__":
	main()


