from __future__ import annotations

import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from manual_publication import (
	ArchiveBackendClient,
	BackendSettings,
	FtpProgress,
	FtpPublisher,
	FtpSettings,
	FtpUploadError,
	ManualPublicationService,
	PublicationPartialFailure,
	PublicationPreflightError,
	PublicationResult,
	RemoteFileInfo,
	RemoteFilePolicy,
)
from publication_queue import PendingArchive, PublicationQueue, PublicationQueueError


PUBLICATION_SETTING_VARIABLES = {
	"ftp_host": "var_ftp_host",
	"ftp_port": "var_ftp_port",
	"ftp_username": "var_ftp_username",
	"ftp_remote_directory": "var_ftp_remote_directory",
	"ftp_passive": "var_ftp_passive",
	"backend_url": "var_backend_url",
}


class ManualPublicationGuiMixin:
	def __init__(self, root: tk.Tk) -> None:
		self.SETTING_VARIABLES = {
			**getattr(self, "SETTING_VARIABLES", {}),
			**PUBLICATION_SETTING_VARIABLES,
		}
		self.var_ftp_host = tk.StringVar(master=root)
		self.var_ftp_port = tk.StringVar(master=root, value="21")
		self.var_ftp_username = tk.StringVar(master=root)
		self.var_ftp_password = tk.StringVar(master=root)
		self.var_ftp_remote_directory = tk.StringVar(master=root, value="/")
		self.var_ftp_passive = tk.BooleanVar(master=root, value=True)
		self.var_backend_url = tk.StringVar(master=root, value="http://127.0.0.1:8780")
		self.var_backend_token = tk.StringVar(master=root)
		self.var_publication_progress = tk.DoubleVar(master=root, value=0.0)
		self.var_publication_status = tk.StringVar(master=root, value="尚未生成待归档包")
		self.var_publication_detail = tk.StringVar(master=root, value="")
		self._publication_active = False
		self._publication_cancel_event = threading.Event()
		self._publication_events: queue.Queue[tuple[str, tuple[object, ...]]] = queue.Queue()
		self._publication_started_at = 0.0
		self._pending_ftp_settings: FtpSettings | None = None
		self._pending_backend_settings: BackendSettings | None = None
		self._pending_retry_item: PendingArchive | None = None
		self._retry_confirm_state = "disabled"
		self._publication_poll_after_id: str | None = None
		self._publication_queue_error = ""
		try:
			self._publication_queue: PublicationQueue | None = PublicationQueue()
		except PublicationQueueError as error:
			self._publication_queue = None
			self._publication_queue_error = str(error)
		super().__init__(root)
		self._build_publication_config_tab()
		self._refresh_sync_queue_button()
		self.root.bind("<Destroy>", self._on_publication_root_destroyed, add="+")
		self._publication_poll_after_id = self.root.after(100, self._poll_publication_events)

	def _build_daily_tab(self, parent: ttk.Frame) -> None:
		super()._build_daily_tab(parent)
		for widget in parent.grid_slaves():
			row = int(widget.grid_info().get("row", 0))
			if row >= 2:
				widget.grid_configure(row=row + 1)
		parent.rowconfigure(2, weight=0)
		parent.rowconfigure(3, weight=1)

		publication_frame = ttk.LabelFrame(parent, text="手动归档", padding=10)
		publication_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))
		publication_frame.columnconfigure(0, weight=1)

		button_row = ttk.Frame(publication_frame)
		button_row.grid(row=0, column=0, sticky="ew")
		button_row.columnconfigure(0, weight=1)
		self.btn_retry_sync = ttk.Button(
			button_row,
			text="待同步 0",
			command=self.on_retry_sync,
			state="disabled",
		)
		self.btn_retry_sync.grid(row=0, column=0, sticky="w")
		self.btn_open_report = ttk.Button(
			button_row,
			text="打开 Report",
			command=self.open_current_report,
			state="disabled",
		)
		self.btn_open_report.grid(row=0, column=1, sticky="e")
		self.btn_confirm_archive = ttk.Button(
			button_row,
			text="确认归档",
			command=self.on_confirm_archive,
			state="disabled",
		)
		self.btn_confirm_archive.grid(row=0, column=2, sticky="e", padx=(8, 0))
		self.btn_cancel_publication = ttk.Button(
			button_row,
			text="取消上传",
			command=self.cancel_publication,
			state="disabled",
		)
		self.btn_cancel_publication.grid(row=0, column=3, sticky="e", padx=(8, 0))

		self.publication_progress = ttk.Progressbar(
			publication_frame,
			mode="determinate",
			maximum=100,
			variable=self.var_publication_progress,
		)
		self.publication_progress.grid(row=1, column=0, sticky="ew", pady=(8, 0))
		ttk.Label(
			publication_frame,
			textvariable=self.var_publication_status,
		).grid(row=2, column=0, sticky="w", pady=(6, 0))
		ttk.Label(
			publication_frame,
			textvariable=self.var_publication_detail,
		).grid(row=3, column=0, sticky="w", pady=(2, 0))

	def _build_publication_config_tab(self) -> None:
		parent = ttk.Frame(self.notebook, padding=12)
		self.notebook.add(parent, text="归档配置")
		parent.columnconfigure(0, weight=1)

		ftp_frame = ttk.LabelFrame(parent, text="FTP", padding=10)
		ftp_frame.grid(row=0, column=0, sticky="ew")
		ftp_frame.columnconfigure(1, weight=1)
		ftp_frame.columnconfigure(3, weight=1)
		ttk.Label(ftp_frame, text="主机").grid(row=0, column=0, sticky="w", padx=(0, 8))
		ttk.Entry(ftp_frame, textvariable=self.var_ftp_host).grid(row=0, column=1, sticky="ew")
		ttk.Label(ftp_frame, text="端口").grid(row=0, column=2, sticky="w", padx=(12, 8))
		ttk.Entry(ftp_frame, textvariable=self.var_ftp_port, width=8).grid(row=0, column=3, sticky="w")
		ttk.Label(ftp_frame, text="用户名").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
		ttk.Entry(ftp_frame, textvariable=self.var_ftp_username).grid(row=1, column=1, sticky="ew", pady=(8, 0))
		ttk.Label(ftp_frame, text="密码").grid(row=1, column=2, sticky="w", padx=(12, 8), pady=(8, 0))
		ttk.Entry(ftp_frame, textvariable=self.var_ftp_password, show="*").grid(
			row=1, column=3, sticky="ew", pady=(8, 0)
		)
		ttk.Label(ftp_frame, text="远端目录").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
		ttk.Entry(ftp_frame, textvariable=self.var_ftp_remote_directory).grid(
			row=2, column=1, columnspan=3, sticky="ew", pady=(8, 0)
		)
		ttk.Checkbutton(
			ftp_frame,
			text="被动模式",
			variable=self.var_ftp_passive,
		).grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 0))

		backend_frame = ttk.LabelFrame(parent, text="网页归档后端", padding=10)
		backend_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
		backend_frame.columnconfigure(1, weight=1)
		tk.Label(backend_frame, text="后端地址").grid(row=0, column=0, sticky="w", padx=(0, 8))
		ttk.Entry(backend_frame, textvariable=self.var_backend_url).grid(row=0, column=1, sticky="ew")
		ttk.Label(backend_frame, text="访问 Token").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
		ttk.Entry(backend_frame, textvariable=self.var_backend_token, show="*").grid(
			row=1, column=1, sticky="ew", pady=(8, 0)
		)

	def _refresh_sync_queue_button(self) -> None:
		if not hasattr(self, "btn_retry_sync"):
			return
		if self._publication_queue is None:
			self.btn_retry_sync.configure(text="待同步不可用", state="disabled")
			return
		try:
			count = self._publication_queue.count()
		except PublicationQueueError as error:
			self._publication_queue_error = str(error)
			self.btn_retry_sync.configure(text="待同步不可用", state="disabled")
			return
		state = "normal" if count > 0 and not self._publication_active else "disabled"
		self.btn_retry_sync.configure(text=f"待同步 {count}", state=state)

	def on_start_packaging(self) -> None:
		if self._publication_active:
			messagebox.showwarning("归档进行中", "请等待当前归档结束或先取消上传。", parent=self.root)
			return
		self._reset_publication_result()
		super().on_start_packaging()
		result = getattr(self, "last_pack_result", None)
		if result is not None:
			self._activate_pack_result(result)
		else:
			self.var_publication_status.set("\u6253\u5305\u672a\u5b8c\u6210")
			self.var_publication_detail.set("\u8bf7\u6839\u636e Result \u65e5\u5fd7\u4fee\u6b63\u540e\u91cd\u8bd5")

	def _activate_pack_result(self, result) -> None:
		self.btn_open_report.configure(state="normal")
		validation = result.report.get("validation", {})
		summary = validation.get("summary", {}) if isinstance(validation, dict) else {}
		error_count = int(summary.get("error_count", 0)) if isinstance(summary, dict) else 0
		warning_count = int(summary.get("warning_count", 0)) if isinstance(summary, dict) else 0
		blocked = result.failure_count > 0 or error_count > 0
		if blocked:
			self.btn_confirm_archive.configure(state="disabled")
			self.var_publication_status.set("Report \u5b58\u5728\u9519\u8bef\uff0c\u7981\u6b62\u5f52\u6863")
			self.var_publication_detail.set(
				f"\u6253\u5305\u5931\u8d25\u6587\u4ef6 {result.failure_count}\uff0c\u6821\u9a8c\u9519\u8bef {error_count}"
			)
			return
		self.btn_confirm_archive.configure(state="normal")
		self.var_publication_status.set("Report \u5f85\u4eba\u5de5\u786e\u8ba4")
		self.var_publication_detail.set(
			f"{Path(result.tar_path).name} \u00b7 {result.success_count} \u4e2a\u6587\u4ef6 \u00b7 {warning_count} \u4e2a\u544a\u8b66"
		)

	def _reset_publication_result(self) -> None:
		self.var_publication_progress.set(0.0)
		self.var_publication_status.set("正在打包")
		self.var_publication_detail.set("")
		if hasattr(self, "btn_open_report"):
			self.btn_open_report.configure(state="disabled")
			self.btn_confirm_archive.configure(state="disabled")
			self.btn_cancel_publication.configure(state="disabled")

	def open_current_report(self) -> None:
		result = getattr(self, "last_pack_result", None)
		if result is None:
			return
		try:
			os.startfile(result.report_path)
		except OSError as error:
			messagebox.showerror("无法打开 Report", str(error), parent=self.root)

	def on_confirm_archive(self) -> None:
		if self._publication_active:
			return
		result = getattr(self, "last_pack_result", None)
		if result is None:
			messagebox.showwarning("没有待归档包", "请先完成本地打包。", parent=self.root)
			return
		try:
			ftp_settings, backend_settings = self._publication_settings()
		except (TypeError, ValueError) as error:
			messagebox.showerror("归档配置无效", str(error), parent=self.root)
			self.notebook.select(self.notebook.tabs()[-1])
			return

		validation = result.report.get("validation", {})
		summary = validation.get("summary", {}) if isinstance(validation, dict) else {}
		warning_count = int(summary.get("warning_count", 0)) if isinstance(summary, dict) else 0
		archive_size = Path(result.tar_path).stat().st_size
		message = (
			f"包名：{Path(result.tar_path).name}\n"
			f"大小：{self._format_bytes(archive_size)}\n"
			f"告警：{warning_count}\n"
			f"FTP：{ftp_settings.host}{ftp_settings.remote_directory}\n\n"
			"确认开始归档？"
		)
		if not messagebox.askyesno("确认归档", message, parent=self.root):
			return

		self._pending_ftp_settings = ftp_settings
		self._pending_backend_settings = backend_settings
		self._publication_active = True
		self._publication_cancel_event = threading.Event()
		self.var_publication_progress.set(0.0)
		self.var_publication_status.set("正在检查 FTP 同名文件")
		self.var_publication_detail.set(Path(result.tar_path).name)
		self.btn_confirm_archive.configure(state="disabled")
		self.btn_cancel_publication.configure(state="normal")
		threading.Thread(target=self._inspect_remote_worker, daemon=True).start()

	def _publication_settings(self) -> tuple[FtpSettings, BackendSettings]:
		password = self.var_ftp_password.get() or os.environ.get("AOV_FTP_PASSWORD", "")
		token = self.var_backend_token.get() or os.environ.get("AOV_BACKEND_TOKEN", "")
		ftp_settings = FtpSettings(
			host=self.var_ftp_host.get().strip(),
			port=int(self.var_ftp_port.get().strip()),
			username=self.var_ftp_username.get().strip(),
			password=password,
			remote_directory=self.var_ftp_remote_directory.get().strip(),
			passive=self.var_ftp_passive.get(),
		)
		backend_settings = BackendSettings(
			self.var_backend_url.get().strip(),
			token,
		)
		return ftp_settings, backend_settings

	def on_retry_sync(self) -> None:
		if self._publication_active or self._publication_queue is None:
			return
		try:
			pending = self._publication_queue.list_pending()
		except PublicationQueueError as error:
			messagebox.showerror("无法读取待同步队列", str(error), parent=self.root)
			return
		if not pending:
			self._refresh_sync_queue_button()
			return
		item = pending[0]
		if not messagebox.askyesno(
			"重试网页同步",
			f"包名：{item.package_id}\n"
			f"已尝试：{item.attempts} 次\n"
			f"后端：{item.backend_url}\n\n"
			"只重试网页归档，不会再次上传 FTP。确认继续？",
			parent=self.root,
		):
			return
		token = self.var_backend_token.get() or os.environ.get("AOV_BACKEND_TOKEN", "")
		self._pending_retry_item = item
		self._retry_confirm_state = str(self.btn_confirm_archive.cget("state"))
		self._publication_active = True
		self.var_publication_progress.set(100.0)
		self.var_publication_status.set("正在重试网页归档")
		self.var_publication_detail.set(item.package_id)
		self.btn_confirm_archive.configure(state="disabled")
		self.btn_cancel_publication.configure(state="disabled")
		self._refresh_sync_queue_button()
		threading.Thread(
			target=self._retry_sync_worker,
			args=(item, BackendSettings(item.backend_url, token)),
			daemon=True,
		).start()

	def _retry_sync_worker(self, item: PendingArchive, settings: BackendSettings) -> None:
		queue_store = self._publication_queue
		if queue_store is None:
			self._emit_publication_event(
				"retry_failure",
				item,
				PublicationQueueError("Publication queue is unavailable."),
				"",
			)
			return
		try:
			result = ArchiveBackendClient().sync_payload(item.payload, settings)
			queue_store.complete(item.idempotency_key)
		except Exception as error:
			queue_error = ""
			try:
				queue_store.mark_failure(item.idempotency_key, str(error))
			except PublicationQueueError as update_error:
				queue_error = str(update_error)
			self._emit_publication_event("retry_failure", item, error, queue_error)
			return
		self._emit_publication_event("retry_complete", item, result)

	def _inspect_remote_worker(self) -> None:
		result = getattr(self, "last_pack_result", None)
		settings = self._pending_ftp_settings
		if result is None or settings is None:
			self._emit_publication_event("failure", PublicationPreflightError("Missing package state."))
			return
		try:
			remote_info = FtpPublisher().inspect(result.tar_path, settings)
		except Exception as error:
			self._emit_publication_event("failure", error)
			return
		self._emit_publication_event("remote_info", remote_info)

	def _handle_remote_info(self, info: RemoteFileInfo) -> None:
		if self._publication_cancel_event.is_set():
			self._finish_cancelled()
			return
		if not info.exists:
			self._start_publish(RemoteFilePolicy.REQUIRE_ABSENT)
			return

		if info.remote_size == info.local_size:
			confirmed = messagebox.askyesno(
				"FTP 已有同名包",
				f"FTP 已存在同名文件，远端与本地大小均为 {self._format_bytes(info.local_size)}。\n\n"
				"确认是同一个包并继续网页归档？",
				parent=self.root,
			)
			if confirmed:
				self._start_publish(RemoteFilePolicy.USE_EXISTING)
			else:
				self._finish_cancelled()
			return

		confirmed = messagebox.askyesno(
			"FTP 同名文件大小不一致",
			f"本地：{self._format_bytes(info.local_size)}\n"
			f"远端：{self._format_bytes(info.remote_size or 0)}\n\n"
			"确认删除远端文件并重新上传？",
			parent=self.root,
		)
		if confirmed:
			self._start_publish(RemoteFilePolicy.REPLACE)
		else:
			self._finish_cancelled()

	def _start_publish(self, policy: RemoteFilePolicy) -> None:
		self._publication_started_at = time.monotonic()
		threading.Thread(target=self._publish_worker, args=(policy,), daemon=True).start()

	def _publish_worker(self, policy: RemoteFilePolicy) -> None:
		result = getattr(self, "last_pack_result", None)
		ftp_settings = self._pending_ftp_settings
		backend_settings = self._pending_backend_settings
		if result is None or ftp_settings is None or backend_settings is None:
			self._emit_publication_event("failure", PublicationPreflightError("Missing publication state."))
			return
		try:
			publication = ManualPublicationService(sync_queue=self._publication_queue).publish(
				archive_path=result.tar_path,
				report_path=result.report_path,
				ftp_settings=ftp_settings,
				backend_settings=backend_settings,
				policy=policy,
				progress=lambda progress: self._emit_publication_event("progress", progress),
				cancel_event=self._publication_cancel_event,
				stage=lambda stage: self._emit_publication_event("stage", stage),
			)
		except Exception as error:
			self._emit_publication_event("failure", error)
			return
		self._emit_publication_event("complete", publication)

	def _emit_publication_event(self, event: str, *args: object) -> None:
		self._publication_events.put((event, args))

	def _poll_publication_events(self) -> None:
		try:
			while True:
				event, args = self._publication_events.get_nowait()
				getattr(self, f"_on_publication_{event}")(*args)
		except queue.Empty:
			pass
		try:
			self._publication_poll_after_id = self.root.after(100, self._poll_publication_events)
		except tk.TclError:
			self._publication_poll_after_id = None

	def _on_publication_root_destroyed(self, event: tk.Event) -> None:
		if event.widget is not self.root or self._publication_poll_after_id is None:
			return
		try:
			self.root.after_cancel(self._publication_poll_after_id)
		except tk.TclError:
			pass
		self._publication_poll_after_id = None

	def _on_publication_remote_info(self, info: RemoteFileInfo) -> None:
		self._handle_remote_info(info)

	def _on_publication_stage(self, stage: str) -> None:
		labels = {
			"preflight": "正在复核 Report 与包体哈希",
			"ftp_upload": "FTP 上传中",
			"backend_archive": "FTP 已完成，正在同步网页归档",
			"complete": "正在完成归档",
		}
		self.var_publication_status.set(labels.get(stage, stage))
		if stage == "backend_archive":
			self.var_publication_progress.set(100.0)
			self.btn_cancel_publication.configure(state="disabled")

	def _on_publication_progress(self, progress: FtpProgress) -> None:
		percent = 100.0 if progress.total_bytes == 0 else (
			progress.transferred_bytes * 100.0 / progress.total_bytes
		)
		self.var_publication_progress.set(min(100.0, percent))
		elapsed = max(0.001, time.monotonic() - self._publication_started_at)
		speed = progress.transferred_bytes / elapsed
		remaining = max(0, progress.total_bytes - progress.transferred_bytes)
		eta = remaining / speed if speed > 0 else 0
		self.var_publication_detail.set(
			f"{self._format_bytes(progress.transferred_bytes)} / "
			f"{self._format_bytes(progress.total_bytes)} · "
			f"{self._format_bytes(speed)}/s · 预计 {eta:.0f} 秒"
		)

	def _on_publication_retry_complete(self, item: PendingArchive, result) -> None:
		self._publication_active = False
		self._pending_retry_item = None
		self.var_publication_progress.set(100.0)
		self.var_publication_status.set("网页归档重试成功")
		self.var_publication_detail.set(f"网页 {result.outcome} · {result.package_id}")
		self.append_log(f"网页归档重试成功：{item.package_id}", "success")
		self.btn_confirm_archive.configure(state=self._retry_confirm_state)
		self._refresh_sync_queue_button()

	def _on_publication_retry_failure(
		self,
		item: PendingArchive,
		error: Exception,
		queue_error: str,
	) -> None:
		self._publication_active = False
		self._pending_retry_item = None
		self.var_publication_progress.set(100.0)
		self.var_publication_status.set("网页归档重试失败")
		detail = str(error)
		if queue_error:
			detail += f" · 队列更新失败：{queue_error}"
		self.var_publication_detail.set(detail)
		self.append_log(f"[归档警告] {item.package_id} 重试失败：{detail}", "warning")
		self.btn_confirm_archive.configure(state=self._retry_confirm_state)
		self._refresh_sync_queue_button()

	def _on_publication_complete(self, result: PublicationResult) -> None:
		self._publication_active = False
		self.var_publication_progress.set(100.0)
		self.var_publication_status.set("归档完成")
		ftp_label = "已上传" if result.ftp.outcome == "uploaded" else "已确认同名文件"
		self.var_publication_detail.set(
			f"FTP {ftp_label} · 网页 {result.archive.outcome} · {result.archive.package_id}"
		)
		self.btn_cancel_publication.configure(state="disabled")
		self.btn_confirm_archive.configure(state="disabled")
		self.append_log(f"归档完成：{result.archive.package_id}", "success")
		self._refresh_sync_queue_button()

	def _on_publication_failure(self, error: Exception) -> None:
		self._publication_active = False
		self.btn_cancel_publication.configure(state="disabled")
		self.btn_confirm_archive.configure(state="normal")
		if isinstance(error, PublicationPartialFailure):
			self.var_publication_progress.set(100.0)
			if error.queued:
				self.var_publication_status.set("FTP 已完成，已加入待同步队列")
				self.var_publication_detail.set(f"{error.backend_error} · 可点击“待同步”重试")
			else:
				self.var_publication_status.set("FTP 已完成，网页归档失败")
				detail = str(error.backend_error)
				if error.queue_error:
					detail += f" · 队列写入失败：{error.queue_error}"
				self.var_publication_detail.set(detail)
			self.append_log(f"[归档警告] {error}", "warning")
			self._refresh_sync_queue_button()
			return
		self.var_publication_status.set("归档失败")
		self.var_publication_detail.set(str(error))
		self.append_log(f"[归档错误] {error}", "error")
		if isinstance(error, FtpUploadError) and error.cleanup_error:
			messagebox.showwarning(
				"FTP 残留文件可能未清理",
				f"归档失败，并且删除远端残留文件失败：\n{error.cleanup_error}",
				parent=self.root,
			)

	def cancel_publication(self) -> None:
		if not self._publication_active:
			return
		self._publication_cancel_event.set()
		self.var_publication_status.set("正在取消上传")
		self.btn_cancel_publication.configure(state="disabled")

	def _finish_cancelled(self) -> None:
		self._publication_active = False
		self.var_publication_status.set("已取消归档")
		self.var_publication_detail.set("")
		self.btn_cancel_publication.configure(state="disabled")
		self.btn_confirm_archive.configure(state="normal")

	def publication_close_allowed(self) -> bool:
		if not self._publication_active:
			return True
		messagebox.showwarning(
			"归档进行中",
			"请先取消上传并等待归档操作结束。",
			parent=self.root,
		)
		return False

	@staticmethod
	def _format_bytes(value: float | int) -> str:
		size = float(value)
		for unit in ("B", "KB", "MB", "GB", "TB"):
			if size < 1024 or unit == "TB":
				return f"{size:.1f} {unit}"
			size /= 1024
		return f"{size:.1f} TB"


__all__ = ["ManualPublicationGuiMixin", "PUBLICATION_SETTING_VARIABLES"]
