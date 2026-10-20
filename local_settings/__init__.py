from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


SETTINGS_SCHEMA_VERSION = 1
SETTINGS_PATH_ENV = "AOV_AUTOPACKER_SETTINGS"

STRING_FIELDS = (
	"local_root",
	"tdr_root",
	"svn_target",
	"svn_exe",
	"svn_username",
	"last_external_revision_spec",
	"last_external_time",
	"scope_roots",
	"package_version",
	"package_region",
	"commit_whitelist",
	"commit_high_risk",
	"ftp_host",
	"ftp_port",
	"ftp_username",
	"ftp_remote_directory",
	"backend_url",
	"backend_token",
)

BOOLEAN_FIELDS = (
	"use_auth_cache",
	"enable_commit_check",
	"enable_region_filter",
	"ftp_passive",
)

# 字符串列表字段（如设置页禁用的校验规则 id 列表）
STRING_LIST_FIELDS = (
	"disabled_rule_ids",
)

# 字符串字典字段（如规则自定义名 {规则id: 名称}）
STRING_DICT_FIELDS = (
	"rule_name_overrides",
)


FTP_PROFILE_REGIONS = frozenset({"TW", "TH", "VN", "ID"})
FTP_PROFILE_STRING_FIELDS = (
	"host",
	"port",
	"username",
	"password",
	"remote_directory",
)

# 内置默认配置：新机器/新用户开箱即用，用户保存的配置逐字段覆盖这里的值。
# 注意：exe 与仓库对外可见，这里的 FTP 账号视为公共账号；各区域值待补充。
DEFAULT_LOCAL_SETTINGS: dict[str, Any] = {
	"svn_exe": "svn",
	"use_auth_cache": True,
	"enable_commit_check": True,
	"enable_region_filter": True,
	"backend_url": "https://aovpacker.run.ingarena.net",
	"ftp_profiles": {
		"TW": {
			"host": "148.222.90.7",
			"port": "21",
			"username": "kgtwops",
			"password": "kgtwops",
			"remote_directory": "/",
			"passive": True,
		},
		"TH": {},
		"VN": {},
		"ID": {},
	},
}


def _sanitize_ftp_profiles(value: Any) -> dict[str, dict[str, str | bool]]:
	if not isinstance(value, Mapping):
		return {}
	profiles: dict[str, dict[str, str | bool]] = {}
	for raw_region, raw_profile in value.items():
		region = str(raw_region).upper()
		if region not in FTP_PROFILE_REGIONS or not isinstance(raw_profile, Mapping):
			continue
		profile: dict[str, str | bool] = {}
		for field in FTP_PROFILE_STRING_FIELDS:
			field_value = raw_profile.get(field)
			if isinstance(field_value, str):
				profile[field] = field_value
		passive = raw_profile.get("passive")
		if isinstance(passive, bool):
			profile["passive"] = passive
		profiles[region] = profile
	return profiles

class LocalSettingsError(ValueError):
	pass


def application_root() -> Path:
	if getattr(sys, "frozen", False):
		return Path(sys.executable).resolve().parent
	module_path = Path(__file__).resolve()
	if module_path.name == "__init__.py":
		return module_path.parent.parent
	return module_path.parent


def default_settings_path() -> Path:
	override = os.environ.get(SETTINGS_PATH_ENV, "").strip()
	if override:
		return Path(override).expanduser()
	return application_root() / "settings.json"


def _sanitize_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
	sanitized: dict[str, Any] = {}
	for key in STRING_FIELDS:
		value = settings.get(key)
		if isinstance(value, str):
			sanitized[key] = value
	for key in BOOLEAN_FIELDS:
		value = settings.get(key)
		if isinstance(value, bool):
			sanitized[key] = value
	for key in STRING_LIST_FIELDS:
		value = settings.get(key)
		if isinstance(value, (list, tuple)):
			sanitized[key] = [str(item) for item in value if isinstance(item, (str, int))]
	for key in STRING_DICT_FIELDS:
		value = settings.get(key)
		if isinstance(value, Mapping):
			sanitized[key] = {
				str(field_key): str(field_value).strip()
				for field_key, field_value in value.items()
				if isinstance(field_key, str) and isinstance(field_value, str) and field_value.strip()
			}
	if "ftp_profiles" in settings:
		sanitized["ftp_profiles"] = _sanitize_ftp_profiles(settings.get("ftp_profiles"))
	return sanitized


def _merge_with_defaults(settings: dict[str, Any]) -> dict[str, Any]:
	"""用户配置覆盖内置默认值；FTP 按区域逐字段合并（用户留空的字段用默认值）。"""
	merged = {key: value for key, value in DEFAULT_LOCAL_SETTINGS.items() if key != "ftp_profiles"}
	merged.update({key: value for key, value in settings.items() if key != "ftp_profiles"})
	default_profiles = DEFAULT_LOCAL_SETTINGS["ftp_profiles"]
	user_profiles = settings.get("ftp_profiles") or {}
	profiles: dict[str, dict[str, str | bool]] = {}
	for region in sorted(FTP_PROFILE_REGIONS):
		default_profile = default_profiles.get(region, {})
		user_profile = user_profiles.get(region, {})
		profile: dict[str, str | bool] = {}
		for field in FTP_PROFILE_STRING_FIELDS:
			user_value = user_profile.get(field)
			if isinstance(user_value, str) and user_value.strip():
				profile[field] = user_value
			else:
				profile[field] = str(default_profile.get(field, ""))
		user_passive = user_profile.get("passive")
		profile["passive"] = user_passive if isinstance(user_passive, bool) else bool(default_profile.get("passive", True))
		profiles[region] = profile
	merged["ftp_profiles"] = profiles
	return merged


def load_local_settings(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
	settings_path = Path(path) if path is not None else default_settings_path()
	try:
		if not settings_path.exists():
			return _merge_with_defaults({})
		document = json.loads(settings_path.read_text(encoding="utf-8"))
	except (OSError, UnicodeError, json.JSONDecodeError) as error:
		raise LocalSettingsError(f"Cannot read local settings: {settings_path}: {error}") from error

	if not isinstance(document, dict):
		raise LocalSettingsError(f"Local settings document must be an object: {settings_path}")
	if document.get("schema_version") != SETTINGS_SCHEMA_VERSION:
		raise LocalSettingsError(
			f"Unsupported local settings schema: {document.get('schema_version')!r}; "
			f"expected {SETTINGS_SCHEMA_VERSION}"
		)
	settings = document.get("settings")
	if not isinstance(settings, dict):
		raise LocalSettingsError(f"Local settings field must be an object: {settings_path}")
	return _merge_with_defaults(_sanitize_settings(settings))


def save_local_settings(
	settings: Mapping[str, Any],
	path: str | os.PathLike[str] | None = None,
) -> Path:
	settings_path = Path(path) if path is not None else default_settings_path()
	document = {
		"schema_version": SETTINGS_SCHEMA_VERSION,
		"settings": _sanitize_settings(settings),
	}
	serialized = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
	temp_path: Path | None = None

	try:
		settings_path.parent.mkdir(parents=True, exist_ok=True)
		temp_path = settings_path.with_name(f".{settings_path.name}.{os.getpid()}.tmp")
		temp_path.write_text(serialized, encoding="utf-8")
		os.replace(temp_path, settings_path)
	except OSError as error:
		raise LocalSettingsError(f"Cannot save local settings: {settings_path}: {error}") from error
	finally:
		if temp_path is not None and temp_path.exists():
			try:
				temp_path.unlink()
			except OSError:
				pass

	return settings_path
