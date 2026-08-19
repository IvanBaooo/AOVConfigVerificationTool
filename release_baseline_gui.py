from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from release_baseline_client import (
	ReleaseBaseline,
	ReleaseBaselineClient,
	ReleaseBaselineClientError,
)


class ReleaseBaselineGuiMixin:
	def __init__(self, root: tk.Tk) -> None:
		self.var_backend_connection_status = tk.StringVar(master=root, value="网页后端：尚未检查")
		self.var_release_baseline_source = tk.StringVar(master=root, value="基线来源：尚未加载")
		self.var_release_baseline_status = tk.StringVar(master=root, value="对外基线尚未检查")
		self._release_baseline_client = ReleaseBaselineClient()
		self._baseline_request_generation = 0
		self._baseline_startup_after_id: str | None = None
		self._baseline_region_after_id: str | None = None
		super().__init__(root)
		self._build_release_baseline_panel()
		self.var_package_region.trace_add("write", self._on_baseline_region_changed)
		self.root.bind("<Destroy>", self._on_baseline_root_destroyed, add="+")
		self._baseline_startup_after_id = self.root.after(700, self._run_startup_baseline_check)

	def _build_daily_tab(self, parent: ttk.Frame) -> None:
		super()._build_daily_tab(parent)
		for widget in parent.grid_slaves():
			row = int(widget.grid_info().get("row", 0))
			if row >= 1:
				widget.grid_configure(row=row + 1)
		for row in range(5):
			parent.rowconfigure(row, weight=0)
		parent.rowconfigure(4, weight=1)

		status_frame = ttk.LabelFrame(parent, text="网页连接", padding=8)
		status_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
		status_frame.columnconfigure(0, weight=1)
		status_frame.columnconfigure(1, weight=1)
		ttk.Label(status_frame, textvariable=self.var_backend_connection_status).grid(
			row=0, column=0, sticky="w"
		)
		ttk.Label(status_frame, textvariable=self.var_release_baseline_source).grid(
			row=0, column=1, sticky="w", padx=(16, 0)
		)
		ttk.Button(
			status_frame,
			text="刷新",
			command=self.refresh_release_baseline,
		).grid(row=0, column=2, sticky="e", padx=(12, 0))

	def _build_release_baseline_panel(self) -> None:
		parent = self.notebook.nametowidget(self.notebook.tabs()[-1])
		panel = ttk.LabelFrame(parent, text="上一次对外基线", padding=10)
		panel.grid(row=5, column=0, sticky="ew", pady=(12, 0))
		panel.columnconfigure(0, weight=1)
		ttk.Label(panel, textvariable=self.var_backend_connection_status).grid(
			row=0, column=0, sticky="w"
		)
		ttk.Button(
			panel,
			text="刷新基线",
			command=self.refresh_release_baseline,
		).grid(row=0, column=1, sticky="e")
		ttk.Label(panel, textvariable=self.var_release_baseline_source).grid(
			row=1, column=0, columnspan=2, sticky="w", pady=(6, 0)
		)
		ttk.Label(panel, textvariable=self.var_release_baseline_status).grid(
			row=2, column=0, columnspan=2, sticky="w", pady=(4, 0)
		)

	def _run_startup_baseline_check(self) -> None:
		self._baseline_startup_after_id = None
		self.refresh_release_baseline()

	def _run_region_baseline_check(self) -> None:
		self._baseline_region_after_id = None
		self.refresh_release_baseline()

	def _on_baseline_region_changed(self, *_args: object) -> None:
		if not hasattr(self, "root"):
			return
		if self._baseline_region_after_id is not None:
			try:
				self.root.after_cancel(self._baseline_region_after_id)
			except tk.TclError:
				pass
		self._baseline_region_after_id = self.root.after_idle(self._run_region_baseline_check)

	def _on_baseline_root_destroyed(self, event: tk.Event) -> None:
		if event.widget is not self.root:
			return
		for callback_id in (self._baseline_startup_after_id, self._baseline_region_after_id):
			if callback_id is None:
				continue
			try:
				self.root.after_cancel(callback_id)
			except tk.TclError:
				pass
		self._baseline_startup_after_id = None
		self._baseline_region_after_id = None

	def refresh_release_baseline(self) -> None:
		region = self.var_package_region.get().strip().upper()
		if region not in {"TW", "TH", "VN", "ID"}:
			return
		self._baseline_request_generation += 1
		generation = self._baseline_request_generation
		self.var_backend_connection_status.set("网页后端：连接检查中")
		self.var_release_baseline_source.set("基线来源：读取中")
		self.var_release_baseline_status.set(f"{region} 基线读取中")
		threading.Thread(
			target=self._release_baseline_worker,
			args=(
				generation,
				region,
				self.var_backend_url.get().strip(),
				self.var_backend_token.get(),
			),
			daemon=True,
		).start()

	def _release_baseline_worker(
		self,
		generation: int,
		region: str,
		base_url: str,
		access_token: str,
	) -> None:
		try:
			health = self._release_baseline_client.check_health(base_url=base_url)
		except ReleaseBaselineClientError as error:
			callback = self._apply_release_baseline_error
			args = (generation, region, str(error), False, base_url, False)
		else:
			try:
				baseline = self._release_baseline_client.fetch(
					base_url=base_url,
					region_code=region,
					access_token=access_token,
				)
			except ReleaseBaselineClientError as error:
				callback = self._apply_release_baseline_error
				args = (generation, region, str(error), True, base_url, health.auth_required)
			else:
				callback = self._apply_release_baseline
				args = (generation, baseline, base_url, health.auth_required)
		try:
			self.root.after(0, callback, *args)
		except (RuntimeError, tk.TclError):
			return

	def _connected_label(self, base_url: str, auth_required: bool) -> str:
		auth_label = "需要 Token" if auth_required else "无需 Token"
		return f"网页后端：已连接 · {auth_label} · {base_url}"

	def _apply_release_baseline(
		self,
		generation: int,
		baseline: ReleaseBaseline,
		base_url: str = "",
		auth_required: bool = False,
	) -> None:
		if generation != self._baseline_request_generation:
			return
		current_region = self.var_package_region.get().strip().upper()
		if baseline.region_code != current_region:
			return
		self.var_last_external_revision_spec.set(baseline.released_revision_spec)
		self.var_last_external_time.set(baseline.release_time)
		self.var_backend_connection_status.set(self._connected_label(base_url, auth_required))
		self.var_release_baseline_source.set(
			f"基线来源：网页后端 · {baseline.region_code} {baseline.released_revision_spec}"
		)
		self.var_release_baseline_status.set(
			f"归档时间 {baseline.release_time} · 来源包 {baseline.package_id}"
		)
		self.append_log(
			f"已加载网页端基线：{baseline.region_code} {baseline.released_revision_spec} "
			f"({baseline.package_id})",
			"success",
		)

	def _apply_release_baseline_error(
		self,
		generation: int,
		region: str,
		message: str,
		connected: bool = False,
		base_url: str = "",
		auth_required: bool = False,
	) -> None:
		if generation != self._baseline_request_generation:
			return
		if connected:
			self.var_backend_connection_status.set(self._connected_label(base_url, auth_required))
		else:
			self.var_backend_connection_status.set(f"网页后端：连接失败 · {base_url}")
		self.var_release_baseline_source.set(f"基线来源：手工输入 · {region}")
		self.var_release_baseline_status.set(f"未自动加载：{message}")
		self.append_log(f"[基线提示] {region}：{message}", "warning")

	def _on_publication_complete(self, result) -> None:
		super()._on_publication_complete(result)
		self.refresh_release_baseline()

	def _on_publication_retry_complete(self, item, result) -> None:
		super()._on_publication_retry_complete(item, result)
		self.refresh_release_baseline()


__all__ = ["ReleaseBaselineGuiMixin"]