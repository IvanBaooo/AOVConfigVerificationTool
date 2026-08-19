from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import Dict, Optional

from svn_path_policy import parse_whitelist_patterns
from validation_rule_client import (
	RuleLoadResult,
	ValidationRuleClient,
	ValidationRuleClientError,
	built_in_rule_set,
)


def apply_rule_set_to_validation_config(
	validation_config: Optional[Dict[str, object]],
	load_result: RuleLoadResult,
) -> Dict[str, object]:
	config = dict(validation_config or {})
	commit_value = config.get("commit_record")
	commit_record = dict(commit_value) if isinstance(commit_value, dict) else {}
	rules = load_result.rule_set.get("rules", {})
	rules = rules if isinstance(rules, dict) else {}
	remote_whitelist = rules.get("whitelist_paths", [])
	local_whitelist = commit_record.get("whitelist_paths", [])
	commit_record["whitelist_paths"] = parse_whitelist_patterns([
		*(remote_whitelist if isinstance(remote_whitelist, list) else []),
		*(local_whitelist if isinstance(local_whitelist, list) else []),
	])
	path_mappings = rules.get("path_mappings", [])
	commit_record["path_mappings"] = [
		dict(item) for item in path_mappings
		if isinstance(item, dict)
	] if isinstance(path_mappings, list) else []
	config["commit_record"] = commit_record
	if "content_checks" in rules:
		content_checks = rules.get("content_checks", [])
		config["content_checks"] = [
			dict(item) for item in content_checks
			if isinstance(item, dict)
		] if isinstance(content_checks, list) else []
	config["rule_set"] = {
		"rule_set_id": load_result.rule_set.get("rule_set_id", ""),
		"version": load_result.rule_set.get("version", ""),
		"rule_hash": load_result.rule_set.get("rule_hash", ""),
		"published_at": load_result.rule_set.get("published_at", ""),
		"region_code": load_result.rule_set.get("region_code", ""),
		"source": load_result.source,
		"message": load_result.message,
	}
	return config


class ValidationRuleGuiMixin:
	def __init__(self, root: tk.Tk) -> None:
		self.var_rule_status = tk.StringVar(master=root, value="规则尚未检查")
		self._validation_rule_client = ValidationRuleClient()
		self._active_validation_rules: dict[str, RuleLoadResult] = {}
		self._rule_request_generation = 0
		self._rule_startup_after_id: str | None = None
		self._rule_region_after_id: str | None = None
		super().__init__(root)
		self._build_validation_rule_tab()
		self.var_package_region.trace_add("write", self._on_rule_region_changed)
		self.root.bind("<Destroy>", self._on_rule_root_destroyed, add="+")
		self._rule_startup_after_id = self.root.after(500, self._run_startup_rule_check)

	def _build_validation_rule_tab(self) -> None:
		parent = self.notebook.nametowidget(self.notebook.tabs()[-1])
		parent.columnconfigure(0, weight=1)

		status_frame = ttk.LabelFrame(parent, text="校验规则", padding=10)
		status_frame.grid(row=3, column=0, sticky="ew", pady=(12, 0))
		status_frame.columnconfigure(0, weight=1)
		ttk.Label(status_frame, textvariable=self.var_rule_status).grid(
			row=0, column=0, sticky="w"
		)
		ttk.Button(
			status_frame,
			text="检查规则更新",
			command=self.check_validation_rules,
		).grid(row=0, column=1, sticky="e")

		ttk.Label(
			parent,
			text="启动时自动检查；连接失败时使用该区域上次成功缓存，没有缓存时使用程序内置规则。",
		).grid(row=4, column=0, sticky="w", pady=(10, 0))

	def _run_startup_rule_check(self) -> None:
		self._rule_startup_after_id = None
		self.check_validation_rules()

	def _run_region_rule_check(self) -> None:
		self._rule_region_after_id = None
		self.check_validation_rules()

	def _on_rule_region_changed(self, *_args: object) -> None:
		if not hasattr(self, "root"):
			return
		if self._rule_region_after_id is not None:
			try:
				self.root.after_cancel(self._rule_region_after_id)
			except tk.TclError:
				pass
		self._rule_region_after_id = self.root.after_idle(self._run_region_rule_check)

	def _on_rule_root_destroyed(self, event: tk.Event) -> None:
		if event.widget is not self.root:
			return
		for callback_id in (self._rule_startup_after_id, self._rule_region_after_id):
			if callback_id is None:
				continue
			try:
				self.root.after_cancel(callback_id)
			except tk.TclError:
				pass
		self._rule_startup_after_id = None
		self._rule_region_after_id = None

	def check_validation_rules(self) -> None:
		region = self.var_package_region.get().strip().upper()
		if region not in {"TW", "TH", "VN", "ID"}:
			return
		base_url = self.var_backend_url.get().strip()
		access_token = self.var_backend_token.get()
		self._rule_request_generation += 1
		generation = self._rule_request_generation
		self.var_rule_status.set(f"{region} 规则检查中")
		threading.Thread(
			target=self._validation_rule_worker,
			args=(generation, region, base_url, access_token),
			daemon=True,
		).start()

	def _validation_rule_worker(
		self,
		generation: int,
		region: str,
		base_url: str,
		access_token: str,
	) -> None:
		result = self._validation_rule_client.resolve(
			base_url=base_url,
			region_code=region,
			access_token=access_token,
		)
		try:
			self.root.after(0, self._apply_validation_rule_result, generation, region, result)
		except (RuntimeError, tk.TclError):
			return

	def _apply_validation_rule_result(
		self,
		generation: int,
		region: str,
		result: RuleLoadResult,
	) -> None:
		if generation != self._rule_request_generation:
			return
		previous = self._active_validation_rules.get(region)
		self._active_validation_rules[region] = result
		version = str(result.rule_set.get("version") or "")
		source_labels = {
			"remote": "后端最新规则",
			"local_cache": "本地缓存",
			"built_in": "内置规则",
		}
		source_label = source_labels.get(result.source, result.source)
		self.var_rule_status.set(f"{region} · v{version} · {source_label}")
		previous_version = str(previous.rule_set.get("version") or "") if previous else ""
		if result.source == "remote" and previous_version and previous_version != version:
			self.append_log(f"校验规则已更新：{region} {previous_version} -> {version}", "success")
		elif result.source == "remote":
			self.append_log(f"校验规则已加载：{region} v{version}", "success")
		else:
			self.append_log(
				f"校验规则使用{source_label}：{region} v{version}；{result.message}",
				"warning",
			)

	def _local_rule_result(self, region: str) -> RuleLoadResult:
		active = self._active_validation_rules.get(region)
		if active is not None:
			return active
		try:
			cached = self._validation_rule_client.cache.load(region)
		except ValidationRuleClientError as error:
			return RuleLoadResult(built_in_rule_set(region), "built_in", str(error))
		if cached is not None:
			return RuleLoadResult(cached, "local_cache", "Startup update has not completed.")
		return RuleLoadResult(
			built_in_rule_set(region),
			"built_in",
			"Startup update has not completed and no cache is available.",
		)

	def build_validation_config(self, raw_input_text: str):
		base = super().build_validation_config(raw_input_text)
		region = self.var_package_region.get().strip().upper() or "TW"
		return apply_rule_set_to_validation_config(base, self._local_rule_result(region))
