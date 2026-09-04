from __future__ import annotations

import json
import os
import sys
import time
import traceback
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable, Mapping

from local_settings import load_local_settings, save_local_settings
from manual_publication import (
	ArchiveBackendClient,
	BackendSettings,
	FtpPublisher,
	FtpSettings,
	ManualPublicationService,
	RemoteFilePolicy,
)
from package_region_target import scope_root_for_region, svn_target_for_region
from packer_core import PackagingError
from packer_mvp_region_named import pack_incremental_package_mvp_region_named
from publication_queue import PublicationQueue
from release_baseline_client import ReleaseBaselineClient
from rules.client import (
	RuleLoadResult,
	ValidationRuleClient,
	ValidationRuleClientError,
	built_in_rule_set,
)
from rules.registry import (
	all_rule_specs,
	apply_disabled_rules,
	apply_rule_name_overrides,
	default_incident_content_checks,
)
from svn_cli_log_auth import fetch_svn_log_with_auth
from svn_commit_pack_input import build_packer_file_list_from_svn_log
from svn_commit_validation import RevisionSpecError, normalize_fixed_path
from svn_dtxml_changeset import infer_tdr_svn_target
from svn_pack_source import PackSourceError, historical_pack_root, inspect_pack_source
from changeset_modules import ModuleContext, run_changeset_modules
from showcase_studio import (
	BYTES_BY_DFXML,
	REGION as SHOWCASE_REGION,
	REPO_PREFIX as SHOWCASE_REPO_PREFIX,
	build_showcase_changeset,
	diff_workspace,
	init_workspace,
	list_rows as showcase_list_rows,
	list_sheets as showcase_list_sheets,
	list_tables as showcase_list_tables,
	update_row as showcase_update_row,
	delete_row as showcase_delete_row,
	add_row as showcase_add_row,
	showcase_status,
	synthesize_svn_log,
	workspace_layout,
)
from validation_full_mvp_optimized import run_full_mvp_validations_optimized


SUPPORTED_REGIONS = ("TW", "TH", "VN", "ID")
EventCallback = Callable[[str, Mapping[str, object]], None]


def _string(value: object) -> str:
	return value.strip() if isinstance(value, str) else ""


def _boolean(value: object, default: bool = False) -> bool:
	return value if isinstance(value, bool) else default


def _split_lines(value: object) -> list[str]:
	text = _string(value)
	return [
		item.strip()
		for item in text.replace("；", "\n").replace("，", "\n").replace(",", "\n").splitlines()
		if item.strip() and not item.strip().startswith("#")
	]


def renderer_settings(settings: Mapping[str, object]) -> dict[str, object]:
	"""Return local settings without exposing persisted passwords to the renderer."""
	result = dict(settings)
	result.pop("svn_password", None)
	profiles = settings.get("ftp_profiles")
	safe_profiles: dict[str, dict[str, object]] = {}
	if isinstance(profiles, Mapping):
		for region in SUPPORTED_REGIONS:
			profile = profiles.get(region)
			if not isinstance(profile, Mapping):
				continue
			safe_profile = {
				key: value
				for key, value in profile.items()
				if key != "password"
			}
			safe_profile["password_configured"] = bool(_string(profile.get("password")))
			safe_profiles[region] = safe_profile
	result["ftp_profiles"] = safe_profiles
	return result


def cached_rule_set_info(project_root: str | Path, region: str) -> dict[str, object] | None:
	"""读取本地缓存规则集元信息（只读文件，不请求后端）；缺失或损坏时返回 None。"""
	cache_path = Path(project_root) / "rules" / "cached_rule_set.json"
	try:
		data = json.loads(cache_path.read_text(encoding="utf-8"))
	except (OSError, ValueError):
		return None
	regions = data.get("regions") if isinstance(data, Mapping) else None
	if not isinstance(regions, Mapping):
		return None
	rule_set = regions.get(str(region).upper())
	if not isinstance(rule_set, Mapping):
		return None
	return {
		"region_code": _string(rule_set.get("region_code")) or str(region).upper(),
		"rule_set_id": _string(rule_set.get("rule_set_id")),
		"version": _string(rule_set.get("version")),
		"published_at": _string(rule_set.get("published_at")),
	}


def merge_settings(
	existing: Mapping[str, object],
	incoming: Mapping[str, object],
) -> dict[str, object]:
	merged = dict(existing)
	for key, value in incoming.items():
		if key not in {"ftp_profiles", "svn_password"}:
			merged[key] = value
	merged.pop("svn_password", None)

	existing_profiles = existing.get("ftp_profiles")
	stored_profiles = dict(existing_profiles) if isinstance(existing_profiles, Mapping) else {}
	incoming_profiles = incoming.get("ftp_profiles")
	if isinstance(incoming_profiles, Mapping):
		for raw_region, raw_profile in incoming_profiles.items():
			region = str(raw_region).upper()
			if region not in SUPPORTED_REGIONS or not isinstance(raw_profile, Mapping):
				continue
			previous = stored_profiles.get(region)
			profile = dict(previous) if isinstance(previous, Mapping) else {}
			for key, value in raw_profile.items():
				if key not in {"password_configured", "password"}:
					profile[key] = value
			password = raw_profile.get("password")
			if isinstance(password, str) and password:
				profile["password"] = password
			elif raw_profile.get("clear_password") is True:
				profile["password"] = ""
			stored_profiles[region] = profile
	merged["ftp_profiles"] = stored_profiles
	return merged


def build_validation_config(payload: Mapping[str, object], svn_log_text: str) -> dict[str, object]:
	region = _string(payload.get("region")).upper() or "TW"
	if region not in SUPPORTED_REGIONS:
		raise PackagingError(f"Unsupported package region: {region}")
	input_method = _string(payload.get("input_method")) or "revision_spec"
	commit_record: dict[str, object] = {
		"enabled": _boolean(payload.get("enable_commit_check"), True),
		"input_method": input_method,
		"current_revision_spec": _string(payload.get("current_revision_spec")),
		"last_external_revision_spec": _string(payload.get("last_external_revision_spec")),
		"last_external_time": _string(payload.get("last_external_time")),
		"scope_roots": _split_lines(payload.get("scope_roots")) or [scope_root_for_region(region)],
		"whitelist_paths": _split_lines(payload.get("commit_whitelist")),
		"package_region_filter_enabled": _boolean(payload.get("enable_region_filter"), True),
	}
	if input_method == "revision_spec":
		commit_record.update(
			{
				"svn_log_text": svn_log_text,
				"svn_log_source": _string(payload.get("svn_log_source")) or "auto_svn_cli",
				"svn_target": _string(payload.get("svn_target")),
				"svn_exe": _string(payload.get("svn_exe")) or "svn",
				"svn_auth_cache": _boolean(payload.get("use_auth_cache"), True),
			}
		)
		username = _string(payload.get("svn_username"))
		if username:
			commit_record["svn_username"] = username

	config: dict[str, object] = {
		"region_code": region,
		"package_region_code": region,
		"package_version": _string(payload.get("package_version")),
		"package_region_filter_enabled": _boolean(payload.get("enable_region_filter"), True),
		"commit_record": commit_record,
	}
	tdr_root = _string(payload.get("tdr_root"))
	if tdr_root:
		config["tdr_root"] = tdr_root
	if input_method == "revision_spec":
		svn_target = _string(payload.get("svn_target")) or svn_target_for_region(region)
		config["dtxml_diff"] = {
			"enabled": _boolean(payload.get("enable_dtxml_diff"), True),
			"current_revision_spec": _string(payload.get("current_revision_spec")),
			"svn_log_text": svn_log_text,
			"tdr_svn_target": infer_tdr_svn_target(svn_target),
			"svn_exe": _string(payload.get("svn_exe")) or "svn",
			"svn_username": _string(payload.get("svn_username")),
			"svn_password": _string(payload.get("svn_password")),
			"svn_auth_cache": _boolean(payload.get("use_auth_cache"), True),
			"region_code": region,
		}
	skin_validation_enabled = _boolean(payload.get("enable_skin_validation"), False)
	if skin_validation_enabled:
		start = _string(payload.get("window_start"))
		end = _string(payload.get("window_end"))
		if not start or not end:
			raise PackagingError("Content validation requires a start and end time.")
		config["check_window"] = {
			"start_time": start,
			"end_time": end,
			"source": "electron_local",
		}
		if tdr_root:
			config["tdr_root"] = tdr_root
	if "content_checks" not in config:
		content_checks = default_incident_content_checks()
		if skin_validation_enabled:
			# 保持皮肤预检原有行为：注入 content_checks 后需显式携带 skin 规则，
			# 否则 validation_mvp 会以 content_check_disabled 跳过。
			content_checks = [{
				"id": "skin-sale-window",
				"type": "skin_sale_window",
				"enabled": True,
				"name": "英雄皮肤上下架与促销关联",
				"dtxml_path": "/Xml/Garena/{region}/CommonCore/英雄皮肤促销表.dtxml",
				"main_sheet": "svr下发皮肤上下架表",
				"promotion_sheet": "svr下发皮肤促销特卖",
				"trigger_paths": [
					"/英雄皮肤促销表.dtxml",
					"/Databin/Server/Shop/SvrHeroSkinShop.xml",
					"/Databin/Server/Shop/SvrHeroSkinShop.bytes",
				],
			}, *content_checks]
		config["content_checks"] = content_checks
	# 叠加本地规则开关（后端默认、本地叠加）：设置页禁用的规则本次不执行
	content_checks_value = config.get("content_checks")
	if isinstance(content_checks_value, list):
		content_checks_value = apply_disabled_rules(content_checks_value, payload.get("disabled_rule_ids"))
		config["content_checks"] = apply_rule_name_overrides(content_checks_value, payload.get("rule_name_overrides"))
	return config


def _module_detail_lists(module_analysis: object) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
	activity_details: list[dict[str, object]] = []
	content_details: list[dict[str, object]] = []
	if isinstance(module_analysis, dict):
		for module in module_analysis.get("modules", []):
			if not isinstance(module, dict):
				continue
			module_id = str(module.get("module", ""))
			module_name = str(module.get("name", ""))
			for item in module.get("items", []):
				if not isinstance(item, dict):
					continue
				detail = {
					"module": module_id,
					"module_name": module_name,
					"object_id": item.get("object_id", ""),
					"object_name": item.get("name", ""),
					"object_type": item.get("object_type", ""),
					"activity_type": item.get("activity_type", ""),
					"direct_change": bool(item.get("changes")),
					"display_lines": item.get("display_lines", []),
				}
				content_details.append(detail)
				if module_id == "activity":
					activity_details.append({
						"activity_id": detail["object_id"],
						"activity_name": detail["object_name"],
						"activity_type": detail["activity_type"],
						"direct_change": detail["direct_change"],
						"display_lines": detail["display_lines"],
					})
	return activity_details, content_details


class ElectronBridgeService:
	def __init__(self, project_root: str | Path | None = None) -> None:
		self.project_root = Path(project_root or Path(__file__).resolve().parent)
		self.settings_path = self.project_root / "settings.json"
		self.output_parent = self.project_root / "output"
		self.last_pack_result = None
		self.queue = PublicationQueue(self.project_root / "publication_queue.sqlite3")

	def dispatch(
		self,
		command: str,
		payload: Mapping[str, object],
		emit: EventCallback,
	) -> dict[str, object]:
		handler = getattr(self, f"command_{command}", None)
		if handler is None:
			raise ValueError(f"Unknown Electron bridge command: {command}")
		return handler(payload, emit)

	def command_bootstrap(self, _payload: Mapping[str, object], _emit: EventCallback) -> dict[str, object]:
		settings = load_local_settings(self.settings_path)
		region = _string(settings.get("package_region")).upper() or "TW"
		return {
			"settings": renderer_settings(settings),
			"settings_path": str(self.settings_path),
			"output_path": str(self.output_parent),
			"pending_sync_count": self.queue.count(),
			"cached_rule_set": cached_rule_set_info(self.project_root, region),
		}

	def command_save_settings(self, payload: Mapping[str, object], _emit: EventCallback) -> dict[str, object]:
		existing = load_local_settings(self.settings_path)
		settings_value = payload.get("settings")
		if not isinstance(settings_value, Mapping):
			raise ValueError("settings must be an object")
		merged = merge_settings(existing, settings_value)
		save_local_settings(merged, self.settings_path)
		return {"settings": renderer_settings(load_local_settings(self.settings_path))}

	def command_list_validation_rules(self, _payload: Mapping[str, object], _emit: EventCallback) -> dict[str, object]:
		"""设置页「内容校验规则」开关的数据源：返回注册表元数据。"""
		return {"rules": all_rule_specs()}

	def _showcase_root(self, payload: Mapping[str, object]) -> Path:
		custom = _string(payload.get("showcase_dir"))
		return Path(custom) if custom else (self.project_root.parent / "showcase")

	def command_showcase_status(self, payload: Mapping[str, object], _emit: EventCallback) -> dict[str, object]:
		return showcase_status(self._showcase_root(payload))

	def command_init_showcase(self, payload: Mapping[str, object], emit: EventCallback) -> dict[str, object]:
		settings = load_local_settings(self.settings_path)
		source = _string(payload.get("source_tdr_root")) or _string(settings.get("tdr_root"))
		if not source or not Path(source).is_dir():
			raise PackagingError("找不到真实 TdrTable 备份目录，请先在设置页配置 tdr_root。")
		reset = _boolean(payload.get("reset"), False)
		emit("log", {"level": "info", "message": "正在克隆演示数据（APFS clonefile，几乎不占空间）..."})
		result = init_workspace(self._showcase_root(payload), Path(source), force=reset)
		emit("log", {"level": "info", "message": "演示数据就绪，已应用全部演示场景。"})
		return result

	def command_run_showcase(self, payload: Mapping[str, object], emit: EventCallback) -> dict[str, object]:
		settings = load_local_settings(self.settings_path)
		merged = merge_settings(settings, payload)
		root = self._showcase_root(payload)
		layout = workspace_layout(root)
		if not layout["current"].is_dir():
			raise PackagingError("演示工作区未初始化，请先点击「初始化/重置演示数据」。")
		try:
			baseline_revision = int(_string(payload.get("baseline_revision")) or "1738000")
			current_revision = int(_string(payload.get("current_revision_spec")) or str(baseline_revision + 100))
		except ValueError:
			raise PackagingError("基线/当前 revision 必须是数字。")
		if current_revision <= baseline_revision:
			raise PackagingError("当前 revision 必须大于基线 revision。")

		def log(message: str, level: str = "info") -> None:
			emit("log", {"message": message, "level": level})

		log("正在对比 baseline/current 演示目录...")
		changes = diff_workspace(root)
		log_text = synthesize_svn_log(
			changes,
			current_revision=current_revision,
			baseline_revision=baseline_revision,
		)
		log(f"演示提交：{len(changes)} 个 dtxml 变更 · 基线 r{baseline_revision} → 当前 r{current_revision}")

		showcase_payload = dict(merged)
		showcase_payload.update({
			"region": SHOWCASE_REGION,
			"input_method": "revision_spec",
			"current_revision_spec": str(current_revision),
			"last_external_revision_spec": str(baseline_revision),
			"tdr_root": str(layout["current"]),
			"svn_target": SHOWCASE_REPO_PREFIX + "/ServerBytes",
		})
		validation_config = build_validation_config(showcase_payload, log_text)

		log("正在用本地内容源生成 DTXML ChangeSet（不访问 SVN）...")
		change_set = build_showcase_changeset(
			root,
			log_text=log_text,
			current_revision=current_revision,
		)
		changeset_changes = None
		if change_set.get("status") in {"passed", "warning"} and isinstance(change_set.get("changes"), list):
			changeset_changes = change_set["changes"]

		fixed_paths: list[str] = []
		for change in changes:
			for bytes_rel in BYTES_BY_DFXML.get(os.path.basename(change["path"]), []):
				normalized = normalize_fixed_path(f"{SHOWCASE_REPO_PREFIX}/{bytes_rel}")
				if normalized and normalized not in fixed_paths:
					fixed_paths.append(normalized)

		module_context = ModuleContext(tdr_root=str(layout["current"]), region_code=SHOWCASE_REGION)
		log("正在执行规则校验...")
		validation = run_full_mvp_validations_optimized(
			fixed_paths=fixed_paths,
			local_root=str(layout["current"] / "ServerBytes"),
			validation_config=validation_config,
			package_files=[],
			changeset_changes=changeset_changes,
			module_context=module_context,
		)
		log("正在执行业务模块解读...")
		try:
			module_analysis = run_changeset_modules(change_set, validation_config, context=module_context)
		except Exception as error:
			module_analysis = {"status": "error", "message": str(error), "modules": [], "overview": {}}

		files = [
			{
				"fixed_path": path,
				"file_name": os.path.basename(path),
				"directory": os.path.dirname(path),
				"status": "packaged",
				"size": 0,
			}
			for path in fixed_paths
		]
		report = {
			"showcase": True,
			"input": {
				"region_filter": {},
				"baseline_revision": baseline_revision,
				"current_revision": current_revision,
			},
			"files": files,
			"change_set": change_set,
			"validation": validation,
			"module_analysis": module_analysis,
			"status": {"validation_status": "warning"},
		}
		summary = validation.get("summary", {}) if isinstance(validation, dict) else {}
		module_overview = module_analysis.get("overview", {}) if isinstance(module_analysis, dict) else {}
		activity_details, content_details = _module_detail_lists(module_analysis)
		return {
			"package_name": f"SHOWCASE_r{baseline_revision}_r{current_revision}.demo",
			"package_id": f"showcase_r{baseline_revision}_r{current_revision}",
			"tar_path": "",
			"report_path": "",
			"output_dir": str(root),
			"md5": "showcase",
			"success_count": len(files),
			"failure_count": 0,
			"skipped_count": 0,
			"validation": {
				"error_count": int(summary.get("error_count", 0) or 0),
				"warning_count": int(summary.get("warning_count", 0) or 0),
				"confirm_count": int(summary.get("confirm_count", 0) or 0),
			},
			"module_overview": module_overview if isinstance(module_overview, dict) else {},
			"activity_details": activity_details,
			"content_details": content_details,
			"region_filter": {},
			"report": report,
			"can_archive": False,
			"showcase": True,
		}

	def command_showcase_tables(self, payload: Mapping[str, object], _emit: EventCallback) -> dict[str, object]:
		return {"tables": showcase_list_tables(self._showcase_root(payload))}

	def command_showcase_sheets(self, payload: Mapping[str, object], _emit: EventCallback) -> dict[str, object]:
		return {"sheets": showcase_list_sheets(self._showcase_root(payload), _string(payload.get("table")))}

	def command_showcase_rows(self, payload: Mapping[str, object], _emit: EventCallback) -> dict[str, object]:
		return showcase_list_rows(
			self._showcase_root(payload),
			_string(payload.get("table")),
			_string(payload.get("sheet")),
			keyword=_string(payload.get("keyword")),
			offset=int(payload.get("offset") or 0),
			limit=int(payload.get("limit") or 100),
		)

	def command_showcase_update_row(self, payload: Mapping[str, object], _emit: EventCallback) -> dict[str, object]:
		changes = payload.get("changes")
		if not isinstance(changes, dict) or not changes:
			raise PackagingError("没有需要保存的字段变更。")
		return showcase_update_row(
			self._showcase_root(payload),
			_string(payload.get("table")),
			_string(payload.get("sheet")),
			int(payload.get("row_index")),
			changes,
		)

	def command_showcase_delete_row(self, payload: Mapping[str, object], _emit: EventCallback) -> dict[str, object]:
		return showcase_delete_row(
			self._showcase_root(payload),
			_string(payload.get("table")),
			_string(payload.get("sheet")),
			int(payload.get("row_index")),
		)

	def command_showcase_add_row(self, payload: Mapping[str, object], _emit: EventCallback) -> dict[str, object]:
		return showcase_add_row(
			self._showcase_root(payload),
			_string(payload.get("table")),
			_string(payload.get("sheet")),
			int(payload.get("row_index")),
		)

	def command_check_backend(self, payload: Mapping[str, object], _emit: EventCallback) -> dict[str, object]:
		base_url = _string(payload.get("backend_url"))
		health = ReleaseBaselineClient().check_health(base_url=base_url)
		result: dict[str, object] = {
			"connected": True,
			"service": health.service,
			"auth_required": health.auth_required,
		}
		region = _string(payload.get("region")).upper()
		if region in SUPPORTED_REGIONS:
			try:
				baseline = ReleaseBaselineClient().fetch(
					base_url=base_url,
					region_code=region,
					access_token=_string(payload.get("backend_token")),
				)
			except Exception as error:
				result["baseline_error"] = str(error)
			else:
				result["baseline"] = {
					"package_id": baseline.package_id,
					"released_revision_spec": baseline.released_revision_spec,
					"release_time": baseline.release_time,
					"package_version": baseline.package_version,
				}
		return result

	def _ftp_settings(self, region: str, overrides: Mapping[str, object] | None = None) -> FtpSettings:
		settings = load_local_settings(self.settings_path)
		profiles = settings.get("ftp_profiles")
		profile_value = profiles.get(region) if isinstance(profiles, Mapping) else None
		profile = dict(profile_value) if isinstance(profile_value, Mapping) else {}
		if overrides:
			for key, value in overrides.items():
				if value not in (None, ""):
					profile[key] = value
		return FtpSettings(
			host=_string(profile.get("host")),
			port=int(_string(profile.get("port")) or "21"),
			username=_string(profile.get("username")),
			password=_string(profile.get("password")) or os.environ.get("AOV_FTP_PASSWORD", ""),
			remote_directory=_string(profile.get("remote_directory")) or "/",
			passive=_boolean(profile.get("passive"), True),
		)

	def command_check_ftp(self, payload: Mapping[str, object], _emit: EventCallback) -> dict[str, object]:
		region = _string(payload.get("region")).upper()
		if region not in SUPPORTED_REGIONS:
			raise ValueError("Unsupported FTP region")
		overrides = payload.get("profile")
		profile = overrides if isinstance(overrides, Mapping) else None
		FtpPublisher().check_connection(self._ftp_settings(region, profile))
		return {"connected": True, "region": region}

	def _packaging_input(self, payload: Mapping[str, object], emit: EventCallback) -> tuple[str, str]:
		input_method = _string(payload.get("input_method")) or "revision_spec"
		raw_input = _string(payload.get("input_text"))
		if input_method != "revision_spec":
			if not raw_input:
				raise PackagingError("Paste the SVN file list before packaging.")
			return raw_input, ""

		current_spec = _string(payload.get("current_revision_spec"))
		if not current_spec:
			raise PackagingError("Current revision is required. Example: r10001,r10003")
		source = _string(payload.get("svn_log_source")) or "auto"
		if source == "auto":
			configured_target = _string(payload.get("svn_target")) or svn_target_for_region(_string(payload.get("region")))
			target = infer_tdr_svn_target(configured_target)
			emit("log", {"level": "info", "message": "正在读取 SVN 提交记录"})
			result = fetch_svn_log_with_auth(
				svn_target=target,
				current_revision_spec=current_spec,
				last_external_revision_spec=_string(payload.get("last_external_revision_spec")),
				svn_exe=_string(payload.get("svn_exe")) or "svn",
				username=_string(payload.get("svn_username")),
				password=_string(payload.get("svn_password")),
				use_auth_cache=_boolean(payload.get("use_auth_cache"), True),
			)
			emit("log", {"level": "info", "message": "已执行：" + " ".join(result.safe_command)})
			if result.returncode != 0:
				message = result.stderr.strip() or result.stdout.strip() or f"svn log returned {result.returncode}"
				raise PackagingError(f"Cannot read SVN log: {message}")
			raw_input = result.stdout
		elif not raw_input:
			raise PackagingError("Paste svn log -v output or select automatic SVN input.")
		try:
			return build_packer_file_list_from_svn_log(raw_input, current_spec), raw_input
		except RevisionSpecError as error:
			raise PackagingError(str(error)) from error

	def _pull_validation_rules(
		self,
		settings: Mapping[str, object],
		region: str,
	) -> RuleLoadResult:
		"""打包前拉取后端下发的校验规则：remote → local_cache → built_in 逐级回退。"""
		client = ValidationRuleClient()
		base_url = _string(settings.get("backend_url"))
		token = _string(settings.get("backend_token")) or os.environ.get("AOV_BACKEND_TOKEN", "")
		try:
			if base_url:
				return client.resolve(base_url=base_url, region_code=region, access_token=token)
			cached = client.cache.load(region)
			if cached is not None:
				return RuleLoadResult(cached, "local_cache", "未配置 backend_url，使用本地缓存规则")
			return RuleLoadResult(built_in_rule_set(region), "built_in", "未配置 backend_url，使用内置默认规则")
		except ValidationRuleClientError as error:
			return RuleLoadResult(built_in_rule_set(region), "built_in", str(error))

	def _apply_rule_set(
		self,
		validation_config: dict[str, object],
		rule_load: RuleLoadResult,
		settings: Mapping[str, object],
	) -> None:
		"""把拉到的规则集写入 validation_config：规则内容覆盖默认，元数据进 report。

		rule_set 元数据字段与 backend_archive_contract_v1 的校验要求对齐
		（SAFE_ID_PATTERN、64 位 hex rule_hash、RFC3339 published_at、
		source ∈ remote/local_cache/built_in），否则归档会失败。
		"""
		rule_set = rule_load.rule_set
		rules = rule_set.get("rules")
		if isinstance(rules, Mapping):
			remote_checks = rules.get("content_checks")
			if isinstance(remote_checks, list) and remote_checks:
				# 后端下发的 content_checks 覆盖内置默认；本地开关/改名仍在其上叠加。
				overlaid = apply_disabled_rules(remote_checks, settings.get("disabled_rule_ids"))
				validation_config["content_checks"] = apply_rule_name_overrides(
					overlaid, settings.get("rule_name_overrides")
				)
			commit_record = validation_config.get("commit_record")
			if isinstance(commit_record, dict):
				path_mappings = rules.get("path_mappings")
				if isinstance(path_mappings, list) and path_mappings:
					commit_record["path_mappings"] = [
						dict(mapping) for mapping in path_mappings if isinstance(mapping, dict)
					]
				whitelist_paths = rules.get("whitelist_paths")
				if isinstance(whitelist_paths, list) and whitelist_paths:
					commit_record["whitelist_paths"] = [str(path) for path in whitelist_paths]
		validation_config["rule_set"] = {
			"rule_set_id": str(rule_set.get("rule_set_id") or "built-in"),
			"version": str(rule_set.get("version") or "1"),
			"rule_hash": str(rule_set.get("rule_hash") or "0" * 64),
			"published_at": str(rule_set.get("published_at") or "1970-01-01T00:00:00Z"),
			"region_code": str(rule_set.get("region_code") or validation_config.get("region_code") or "TW"),
			"source": rule_load.source,
		}

	def command_pack(self, payload: Mapping[str, object], emit: EventCallback) -> dict[str, object]:
		command_started = time.perf_counter()
		command_stages: dict[str, float] = {}
		self.last_pack_result = None
		settings = load_local_settings(self.settings_path)
		merged = merge_settings(settings, payload)
		save_local_settings(merged, self.settings_path)
		runtime_settings = dict(merged)
		runtime_settings["svn_password"] = _string(payload.get("svn_password"))
		svn_input_started = time.perf_counter()
		svn_text, resolved_log = self._packaging_input(runtime_settings, emit)
		command_stages["svn_input"] = round(time.perf_counter() - svn_input_started, 3)
		validation_config = build_validation_config(runtime_settings, resolved_log)

		def log(message: str, level: str = "info") -> None:
			emit("log", {"message": message, "level": level})

		rule_pull_started = time.perf_counter()
		rule_load = self._pull_validation_rules(runtime_settings, str(validation_config.get("region_code") or "TW"))
		command_stages["rule_pull"] = round(time.perf_counter() - rule_pull_started, 3)
		if rule_load.source == "remote":
			log(f"校验规则：已拉取后端规则集 {rule_load.rule_set.get('rule_set_id')} v{rule_load.rule_set.get('version')}。", "info")
		elif rule_load.source == "local_cache":
			log(f"校验规则：后端不可达，使用本地缓存规则集（{rule_load.message}）。", "warning")
		else:
			log(f"校验规则：使用内置默认规则集（{rule_load.message}）。", "info")
		self._apply_rule_set(validation_config, rule_load, runtime_settings)

		local_root = _string(merged.get("local_root"))
		svn_target = _string(merged.get("svn_target")) or svn_target_for_region(_string(merged.get("region")))
		serverbytes_marker = "/ServerBytes"
		marker_index = svn_target.casefold().find(serverbytes_marker.casefold())
		serverbytes_target = (
			svn_target[: marker_index + len(serverbytes_marker)]
			if marker_index >= 0
			else svn_target.rstrip("/") + serverbytes_marker
		)
		emit("stage", {"stage": "source_check"})
		log("正在检查本地工作副本与目标 revision...", "info")
		source_check_started = time.perf_counter()
		try:
			inspection = inspect_pack_source(
				svn_text=svn_text,
				current_revision_spec=_string(runtime_settings.get("current_revision_spec")),
				content_mode=_string(runtime_settings.get("content_mode")) or "local_latest",
				local_root=local_root,
				svn_target=serverbytes_target,
				svn_exe=_string(runtime_settings.get("svn_exe")) or "svn",
				username=_string(runtime_settings.get("svn_username")),
				password=_string(runtime_settings.get("svn_password")),
				use_auth_cache=_boolean(runtime_settings.get("use_auth_cache"), True),
			)
		except PackSourceError as error:
			raise PackagingError(str(error)) from error
		command_stages["source_check"] = round(time.perf_counter() - source_check_started, 3)
		for warning in inspection.warnings:
			log(warning, "warning")
		if inspection.errors:
			raise PackagingError("；".join(inspection.errors))
		package_source = inspection.to_report()
		validation_config["package_source"] = package_source
		if inspection.historical:
			log(f"历史模式：正在按 r{inspection.target_revision} 精确导出打包文件。", "warning")
			source_context = historical_pack_root(
				inspection,
				svn_text=svn_text,
				svn_target=serverbytes_target,
				cache_root=self.project_root / ".svn_snapshot_cache" / "serverbytes",
				svn_exe=_string(runtime_settings.get("svn_exe")) or "svn",
				username=_string(runtime_settings.get("svn_username")),
				password=_string(runtime_settings.get("svn_password")),
				use_auth_cache=_boolean(runtime_settings.get("use_auth_cache"), True),
				log=log,
			)
		else:
			log("最新模式：本地工作副本已通过分支、修改和更新状态检查。", "success")
			source_context = nullcontext((local_root, {}))

		test_mode = _boolean(runtime_settings.get("test_mode"), False)
		emit("stage", {"stage": "packaging"})
		try:
			materialize_started = time.perf_counter()
			with source_context as (pack_root, source_stats):
				command_stages["historical_export"] = round(time.perf_counter() - materialize_started, 3)
				package_source.update(source_stats)
				result = pack_incremental_package_mvp_region_named(
					svn_text=svn_text,
					local_root=pack_root,
					output_parent=str(self.output_parent / "tests" if test_mode else self.output_parent),
					validation_config=validation_config,
					log=log,
				)
		except PackSourceError as error:
			raise PackagingError(str(error)) from error
		performance = result.report.setdefault("performance", {})
		if isinstance(performance, dict):
			stages = performance.setdefault("stages", {})
			if isinstance(stages, dict):
				stages.update(command_stages)
			performance["total_seconds"] = round(time.perf_counter() - command_started, 3)
		result.report.setdefault("input", {})
		if isinstance(result.report["input"], dict):
			result.report["input"]["execution_mode"] = "test" if test_mode else "package"  # type: ignore[index]
		if test_mode and isinstance(result.report.get("status"), dict):
			result.report["status"]["archive_status"] = "not_required"  # type: ignore[index]
		with open(result.report_path, "w", encoding="utf-8") as report_file:
			json.dump(result.report, report_file, ensure_ascii=False, indent=2)
			report_file.write("\n")
		self.last_pack_result = result
		validation = result.report.get("validation")
		summary = validation.get("summary", {}) if isinstance(validation, dict) else {}
		module_analysis = result.report.get("module_analysis")
		module_overview_value = module_analysis.get("overview", {}) if isinstance(module_analysis, dict) else {}
		module_overview = dict(module_overview_value) if isinstance(module_overview_value, dict) else {}
		if isinstance(module_analysis, dict):
			module_overview["uninterpreted_change_count"] = len(module_analysis.get("uninterpreted_changes", []))
			module_overview["deferred_change_count"] = len(module_analysis.get("deferred_changes", []))
		activity_details = []
		content_details = []
		if isinstance(module_analysis, dict):
			for module in module_analysis.get("modules", []):
				if not isinstance(module, dict):
					continue
				module_id = str(module.get("module", ""))
				module_name = str(module.get("name", ""))
				for item in module.get("items", []):
					if not isinstance(item, dict):
						continue
					detail = {
						"module": module_id,
						"module_name": module_name,
						"object_id": item.get("object_id", ""),
						"object_name": item.get("name", ""),
						"object_type": item.get("object_type", ""),
						"activity_type": item.get("activity_type", ""),
						"direct_change": bool(item.get("changes")),
						"display_lines": item.get("display_lines", []),
					}
					content_details.append(detail)
					if module_id == "activity":
						activity_details.append({
							"activity_id": detail["object_id"],
							"activity_name": detail["object_name"],
							"activity_type": detail["activity_type"],
							"direct_change": detail["direct_change"],
							"display_lines": detail["display_lines"],
						})
		region_filter = result.report.get("input", {}).get("region_filter", {})
		return {
			"package_name": Path(result.tar_path).name,
			"package_id": result.base_name,
			"tar_path": result.tar_path,
			"report_path": result.report_path,
			"output_dir": result.output_dir,
			"md5": result.md5,
			"success_count": result.success_count,
			"failure_count": result.failure_count,
			"skipped_count": result.skipped_count,
			"validation": {
				"error_count": int(summary.get("error_count", 0) or 0),
				"warning_count": int(summary.get("warning_count", 0) or 0),
				"confirm_count": int(summary.get("confirm_count", 0) or 0),
			},
			"module_overview": module_overview,
			"activity_details": activity_details,
			"content_details": content_details,
			"region_filter": region_filter if isinstance(region_filter, dict) else {},
			"package_source": package_source,
			"performance": performance if isinstance(performance, dict) else {},
			"test_mode": test_mode,
			"report": result.report,
			"can_archive": not test_mode and result.failure_count == 0 and int(summary.get("error_count", 0) or 0) == 0,
		}

	def command_inspect_archive(self, payload: Mapping[str, object], _emit: EventCallback) -> dict[str, object]:
		if self.last_pack_result is None:
			raise ValueError("No completed package is available")
		region = _string(payload.get("region")).upper()
		info = FtpPublisher().inspect(self.last_pack_result.tar_path, self._ftp_settings(region))
		return {
			"exists": info.exists,
			"filename": info.filename,
			"remote_size": info.remote_size,
			"local_size": info.local_size,
		}

	def command_publish(self, payload: Mapping[str, object], emit: EventCallback) -> dict[str, object]:
		if self.last_pack_result is None:
			raise ValueError("No completed package is available")
		region = _string(payload.get("region")).upper()
		policy = RemoteFilePolicy(_string(payload.get("policy")) or RemoteFilePolicy.REQUIRE_ABSENT.value)
		settings = load_local_settings(self.settings_path)
		backend = BackendSettings(
			_string(settings.get("backend_url")),
			_string(payload.get("backend_token")) or os.environ.get("AOV_BACKEND_TOKEN", ""),
		)
		service = ManualPublicationService(sync_queue=self.queue)
		result = service.publish(
			archive_path=self.last_pack_result.tar_path,
			report_path=self.last_pack_result.report_path,
			ftp_settings=self._ftp_settings(region),
			backend_settings=backend,
			policy=policy,
			progress=lambda value: emit(
				"progress",
				{
					"transferred_bytes": value.transferred_bytes,
					"total_bytes": value.total_bytes,
					"filename": value.filename,
				},
			),
			stage=lambda value: emit("stage", {"stage": value}),
		)
		return {
			"ftp_outcome": result.ftp.outcome,
			"archive_outcome": result.archive.outcome,
			"package_id": result.archive.package_id,
			"pending_sync_count": self.queue.count(),
		}

	def command_retry_sync(self, payload: Mapping[str, object], _emit: EventCallback) -> dict[str, object]:
		pending = self.queue.list_pending()
		if not pending:
			return {"outcome": "empty", "pending_sync_count": 0}
		item = pending[0]
		settings = BackendSettings(
			item.backend_url,
			_string(payload.get("backend_token")) or os.environ.get("AOV_BACKEND_TOKEN", ""),
		)
		try:
			result = ArchiveBackendClient().sync_payload(item.payload, settings)
		except Exception as error:
			self.queue.mark_failure(item.idempotency_key, str(error))
			raise
		self.queue.complete(item.idempotency_key)
		return {
			"outcome": result.outcome,
			"package_id": result.package_id,
			"pending_sync_count": self.queue.count(),
		}


def run_bridge() -> None:
	service = ElectronBridgeService()

	def write(message: Mapping[str, object]) -> None:
		sys.stdout.write(json.dumps(dict(message), ensure_ascii=False, separators=(",", ":")) + "\n")
		sys.stdout.flush()

	for line in sys.stdin:
		try:
			request = json.loads(line)
			if not isinstance(request, dict):
				raise ValueError("Bridge request must be an object")
			request_id = str(request.get("id") or "")
			command = _string(request.get("command"))
			payload_value = request.get("payload")
			payload = payload_value if isinstance(payload_value, Mapping) else {}

			def emit(event: str, data: Mapping[str, object]) -> None:
				write({"type": "event", "id": request_id, "event": event, "data": dict(data)})

			result = service.dispatch(command, payload, emit)
			write({"type": "response", "id": request_id, "ok": True, "result": result})
		except Exception as error:
			write(
				{
					"type": "response",
					"id": str(locals().get("request_id", "")),
					"ok": False,
					"error": str(error),
					"error_type": type(error).__name__,
					"detail": traceback.format_exc() if os.environ.get("AOV_ELECTRON_DEBUG") else "",
				}
			)


if __name__ == "__main__":
	run_bridge()
