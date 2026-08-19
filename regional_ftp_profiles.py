from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Mapping

from manual_publication import FtpPublisher, FtpSettings


FTP_PROFILE_FIELDS = (
	"host",
	"port",
	"username",
	"password",
	"remote_directory",
	"passive",
)
SUPPORTED_FTP_REGIONS = ("TW", "TH", "VN", "ID")


class RegionalFtpProfileGuiMixin:
	def __init__(self, root: tk.Tk) -> None:
		self._ftp_profiles: dict[str, dict[str, str | bool]] = {}
		self._active_ftp_profile_region = ""
		self._ftp_connection_generation = 0
		super().__init__(root)
		self.var_ftp_connection_status = tk.StringVar(master=root, value="FTP 未配置")
		self._build_ftp_profile_actions()
		self.var_package_region.trace_add("write", self._on_ftp_region_changed)
		self._switch_ftp_profile(self.var_package_region.get(), preserve_current=False)

	def apply_local_settings(self, settings: dict[str, object]) -> None:
		profiles = settings.get("ftp_profiles")
		if isinstance(profiles, Mapping):
			self._ftp_profiles = {
				str(region).upper(): dict(profile)
				for region, profile in profiles.items()
				if str(region).upper() in SUPPORTED_FTP_REGIONS and isinstance(profile, Mapping)
			}
		elif isinstance(settings.get("ftp_host"), str) and settings.get("ftp_host"):
			region = str(settings.get("package_region", "TW")).upper()
			if region in SUPPORTED_FTP_REGIONS:
				self._ftp_profiles[region] = {
					"host": str(settings.get("ftp_host", "")),
					"port": str(settings.get("ftp_port", "21")),
					"username": str(settings.get("ftp_username", "")),
					"password": "",
					"remote_directory": str(settings.get("ftp_remote_directory", "/")),
					"passive": bool(settings.get("ftp_passive", True)),
				}
		super().apply_local_settings(settings)

	def collect_local_settings(self) -> dict[str, object]:
		self._store_active_ftp_profile()
		settings = dict(super().collect_local_settings())
		for key in (
			"ftp_host",
			"ftp_port",
			"ftp_username",
			"ftp_remote_directory",
			"ftp_passive",
		):
			settings.pop(key, None)
		settings["ftp_profiles"] = {
			region: dict(profile)
			for region, profile in sorted(self._ftp_profiles.items())
		}
		return settings

	def _build_ftp_profile_actions(self) -> None:
		parent = self.notebook.nametowidget(self.notebook.tabs()[-1])
		action_row = ttk.Frame(parent)
		action_row.grid(row=2, column=0, sticky="ew", pady=(12, 0))
		action_row.columnconfigure(0, weight=1)
		ttk.Label(action_row, textvariable=self.var_ftp_connection_status).grid(
			row=0, column=0, sticky="w"
		)
		ttk.Button(action_row, text="测试连接", command=self.check_current_ftp_connection).grid(
			row=0, column=1, sticky="e"
		)
		ttk.Button(action_row, text="保存当前区域", command=self.save_current_ftp_profile).grid(
			row=0, column=2, sticky="e", padx=(8, 0)
		)

	def _on_ftp_region_changed(self, *_args: object) -> None:
		self._switch_ftp_profile(self.var_package_region.get())

	def _switch_ftp_profile(self, region: str, *, preserve_current: bool = True) -> None:
		region = region.strip().upper()
		if region not in SUPPORTED_FTP_REGIONS:
			return
		if preserve_current:
			self._store_active_ftp_profile()
		profile = self._ftp_profiles.get(region, {})
		self.var_ftp_host.set(str(profile.get("host", "")))
		self.var_ftp_port.set(str(profile.get("port", "21")))
		self.var_ftp_username.set(str(profile.get("username", "")))
		self.var_ftp_password.set(str(profile.get("password", "")))
		self.var_ftp_remote_directory.set(str(profile.get("remote_directory", "/")))
		self.var_ftp_passive.set(bool(profile.get("passive", True)))
		self._active_ftp_profile_region = region
		self.check_current_ftp_connection()

	def _store_active_ftp_profile(self) -> None:
		region = self._active_ftp_profile_region
		if region not in SUPPORTED_FTP_REGIONS:
			return
		self._ftp_profiles[region] = {
			"host": self.var_ftp_host.get().strip(),
			"port": self.var_ftp_port.get().strip() or "21",
			"username": self.var_ftp_username.get().strip(),
			"password": self.var_ftp_password.get(),
			"remote_directory": self.var_ftp_remote_directory.get().strip() or "/",
			"passive": bool(self.var_ftp_passive.get()),
		}

	def save_current_ftp_profile(self) -> None:
		self._store_active_ftp_profile()
		if self.save_current_settings():
			self.check_current_ftp_connection()

	def check_current_ftp_connection(self) -> None:
		region = self.var_package_region.get().strip().upper()
		try:
			settings = self._publication_ftp_settings()
		except (TypeError, ValueError) as error:
			self.var_ftp_connection_status.set(f"{region} FTP 未配置：{error}")
			return
		self._ftp_connection_generation += 1
		generation = self._ftp_connection_generation
		self.var_ftp_connection_status.set(f"{region} FTP 连接检查中")
		threading.Thread(
			target=self._ftp_connection_worker,
			args=(region, generation, settings),
			daemon=True,
		).start()

	def _publication_ftp_settings(self) -> FtpSettings:
		return FtpSettings(
			host=self.var_ftp_host.get().strip(),
			port=int(self.var_ftp_port.get().strip()),
			username=self.var_ftp_username.get().strip(),
			password=self.var_ftp_password.get(),
			remote_directory=self.var_ftp_remote_directory.get().strip(),
			passive=self.var_ftp_passive.get(),
		)

	def _ftp_connection_worker(
		self,
		region: str,
		generation: int,
		settings: FtpSettings,
	) -> None:
		try:
			FtpPublisher().check_connection(settings)
		except Exception as error:
			self._emit_publication_event("ftp_connection", region, generation, False, str(error))
			return
		self._emit_publication_event("ftp_connection", region, generation, True, "")

	def _on_publication_ftp_connection(
		self,
		region: str,
		generation: int,
		connected: bool,
		detail: str,
	) -> None:
		if generation != self._ftp_connection_generation:
			return
		if region != self.var_package_region.get().strip().upper():
			return
		if connected:
			self.var_ftp_connection_status.set(f"{region} FTP 已连接")
		else:
			self.var_ftp_connection_status.set(f"{region} FTP 连接失败：{detail}")


__all__ = [
	"FTP_PROFILE_FIELDS",
	"RegionalFtpProfileGuiMixin",
	"SUPPORTED_FTP_REGIONS",
]
