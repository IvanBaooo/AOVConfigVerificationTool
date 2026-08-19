from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


SETTINGS_SCHEMA_VERSION = 1
SETTINGS_PATH_ENV = "AOV_AUTOPACKER_SETTINGS"

STRING_FIELDS = frozenset(
	{
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
		"window_start",
		"window_end",
		"commit_whitelist",
		"ftp_host",
		"ftp_port",
		"ftp_username",
		"ftp_remote_directory",
		"backend_url",
	}
)

BOOLEAN_FIELDS = frozenset(
	{
		"use_auth_cache",
		"enable_commit_check",
		"enable_region_filter",
		"enable_skin_validation",
		"ftp_passive",
	}
)


FTP_PROFILE_REGIONS = frozenset({"TW", "TH", "VN", "ID"})
FTP_PROFILE_STRING_FIELDS = (
	"host",
	"port",
	"username",
	"password",
	"remote_directory",
)


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
	if "ftp_profiles" in settings:
		sanitized["ftp_profiles"] = _sanitize_ftp_profiles(settings.get("ftp_profiles"))
	return sanitized


def load_local_settings(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
	settings_path = Path(path) if path is not None else default_settings_path()
	if not settings_path.exists():
		return {}

	try:
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
	return _sanitize_settings(settings)


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

	try:
		settings_path.parent.mkdir(parents=True, exist_ok=True)
		temp_path = settings_path.with_name(f".{settings_path.name}.{os.getpid()}.tmp")
		temp_path.write_text(serialized, encoding="utf-8")
		os.replace(temp_path, settings_path)
	except OSError as error:
		raise LocalSettingsError(f"Cannot save local settings: {settings_path}: {error}") from error
	finally:
		temp_path = locals().get("temp_path")
		if isinstance(temp_path, Path) and temp_path.exists():
			try:
				temp_path.unlink()
			except OSError:
				pass

	return settings_path
