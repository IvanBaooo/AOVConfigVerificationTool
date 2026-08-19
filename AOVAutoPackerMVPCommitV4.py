import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk

from AOVAutoPackerMVPCommit import resource_path
from AOVAutoPackerMVPCommitV3 import AOVAutoPackerMVPCommitV3App
from packer_core import PackagingError
from packer_mvp_full import pack_incremental_package_mvp_full
from svn_cli_log_auth import fetch_svn_log_with_auth
from svn_commit_pack_input import build_packer_file_list_from_svn_log
from svn_commit_validation import RevisionSpecError


class AOVAutoPackerMVPCommitV4App(AOVAutoPackerMVPCommitV3App):
	def __init__(self, root: tk.Tk) -> None:
		super().__init__(root)
		self.root.title("AOVAutoPacker MVP - SVN 自动校验 V4")
		self._insert_svn_auth_frame()

	def _insert_svn_auth_frame(self) -> None:
		for widget in self.main_frame.grid_slaves():
			row = int(widget.grid_info().get("row", 0))
			if row >= 7:
				widget.grid_configure(row=row + 1)

		auth_frame = ttk.LabelFrame(self.main_frame, text="SVN 认证（自动模式可选）", padding=8)
		auth_frame.grid(row=7, column=0, sticky="ew", pady=(10, 0))
		auth_frame.columnconfigure(1, weight=1)
		auth_frame.columnconfigure(3, weight=1)

		self.var_use_auth_cache = tk.BooleanVar(value=True)
		ttk.Checkbutton(auth_frame, text="使用 SVN 认证缓存", variable=self.var_use_auth_cache).grid(
			row=0, column=0, sticky="w", columnspan=4
		)

		ttk.Label(auth_frame, text="用户名：").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0))
		self.var_svn_username = tk.StringVar()
		ttk.Entry(auth_frame, textvariable=self.var_svn_username).grid(row=1, column=1, sticky="ew", pady=(6, 0))

		ttk.Label(auth_frame, text="密码：").grid(row=1, column=2, sticky="w", padx=(12, 8), pady=(6, 0))
		self.var_svn_password = tk.StringVar()
		ttk.Entry(auth_frame, textvariable=self.var_svn_password, show="*").grid(row=1, column=3, sticky="ew", pady=(6, 0))

		ttk.Label(auth_frame, text="密码只用于本次 svn log 调用，不写入 report，也不会打印到日志。").grid(
			row=2, column=0, sticky="w", columnspan=4, pady=(6, 0)
		)

	def _load_svn_log_text_for_revision_mode(self) -> str:
		raw_input = self.txt_package_input.get("1.0", "end").strip("\n")
		if self.var_input_method.get() != "revision_spec":
			self._resolved_svn_log_text = ""
			return raw_input
		if self.var_svn_log_source.get() != "auto":
			self._resolved_svn_log_text = raw_input
			return raw_input

		current_spec = self.var_current_revision_spec.get().strip()
		last_external_spec = self.var_last_external_revision_spec.get().strip()
		target = self.var_svn_target.get().strip() or self.var_local_root.get().strip()
		try:
			result = fetch_svn_log_with_auth(
				svn_target=target,
				current_revision_spec=current_spec,
				last_external_revision_spec=last_external_spec,
				svn_exe=self.var_svn_exe.get().strip() or "svn",
				username=self.var_svn_username.get().strip(),
				password=self.var_svn_password.get(),
				use_auth_cache=self.var_use_auth_cache.get(),
			)
		except FileNotFoundError as err:
			raise PackagingError(f"找不到 SVN 程序：{err}")
		except RevisionSpecError as err:
			raise PackagingError(str(err))

		command_text = " ".join(result.safe_command)
		self.append_log(f"已执行：{command_text}", "info")
		if result.returncode != 0:
			message = result.stderr.strip() or result.stdout.strip() or f"svn log 返回码 {result.returncode}"
			raise PackagingError(f"自动读取 SVN log 失败：{message}")
		if not result.stdout.strip():
			raise PackagingError("自动读取 SVN log 成功，但输出为空。")

		self._resolved_svn_log_text = result.stdout
		return result.stdout

	def build_validation_config(self, raw_input_text: str):
		config = super().build_validation_config(raw_input_text)
		if not config:
			return config
		commit_record = config.get("commit_record")
		if isinstance(commit_record, dict) and self.var_input_method.get() == "revision_spec":
			commit_record["svn_auth_cache"] = self.var_use_auth_cache.get()
			if self.var_svn_username.get().strip():
				commit_record["svn_username"] = self.var_svn_username.get().strip()
			commit_record.pop("svn_password", None)
		return config

	def build_packaging_text(self) -> str:
		raw_input = self._load_svn_log_text_for_revision_mode()
		if self.var_input_method.get() != "revision_spec":
			return raw_input

		current_spec = self.var_current_revision_spec.get().strip()
		if not current_spec:
			raise PackagingError("选择 revision 输入方式时必须填写本次 revision。示例：r10001-r10005 或 r10001,r10003")
		if not raw_input.strip():
			raise PackagingError("选择 revision 输入方式时需要粘贴 svn log -v 内容，或切换为自动执行 svn log。")
		try:
			return build_packer_file_list_from_svn_log(raw_input, current_spec)
		except RevisionSpecError as err:
			raise PackagingError(str(err))

	def on_start_packaging(self) -> None:
		raw_input_text = self.txt_package_input.get("1.0", "end").strip("\n")
		local_root = self.var_local_root.get().strip()
		self._resolved_svn_log_text = ""

		try:
			svn_file_list_text = self.build_packaging_text()
			result = pack_incremental_package_mvp_full(
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

			ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AOVAutoPacker.MVPCommitV4")
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

	AOVAutoPackerMVPCommitV4App(root)
	root.minsize(980, 860)
	root.mainloop()


if __name__ == "__main__":
	main()
