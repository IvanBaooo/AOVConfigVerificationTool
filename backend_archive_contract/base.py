from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any


ARCHIVE_CONTRACT_VERSION = "1.0"
ARCHIVE_RECORD_TYPE = "aov_package_archive"
REGION_CODES = frozenset({"TW", "TH", "VN", "ID"})

CHECK_DETAIL_LIST_LIMIT = 200
CHECK_DETAIL_DENIED_KEYS = frozenset(
	{
		"svn_username",
		"svn_password",
		"svn_log_text",
		"raw_line",
		"local_path",
		"local_root",
	}
)

IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
MD5_PATTERN = re.compile(r"^[a-f0-9]{32}$")
SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"(?i)(?:^|[\s(])(?:[a-z]:[\\/]|\\\\)")


class ArchiveContractError(ValueError):
	pass


def _mapping(value: object) -> Mapping[str, Any]:
	return value if isinstance(value, Mapping) else {}


def _required_text(container: Mapping[str, Any], key: str, field: str | None = None) -> str:
	value = container.get(key)
	if not isinstance(value, str) or not value.strip():
		raise ArchiveContractError(f"Required text field is missing: {field or key}")
	result = value.strip()
	if "\r" in result or "\n" in result or "\x00" in result:
		raise ArchiveContractError(f"Control characters are not allowed: {field or key}")
	return result


def _optional_text(container: Mapping[str, Any], key: str) -> str:
	value = container.get(key)
	if value is None:
		return ""
	if not isinstance(value, str):
		raise ArchiveContractError(f"Expected text field: {key}")
	return value.strip()


def _public_message(value: object) -> str:
	if not isinstance(value, str):
		return ""
	message = value.strip().replace("\r", " ").replace("\n", " ")
	if WINDOWS_ABSOLUTE_PATH_PATTERN.search(message):
		return ""
	return message


def _non_negative_integer(value: object, field: str) -> int:
	if type(value) is not int or value < 0:
		raise ArchiveContractError(f"Expected non-negative integer: {field}")
	return value


def _integer_field(container: Mapping[str, Any], key: str, field: str | None = None) -> int:
	if key not in container:
		raise ArchiveContractError(f"Required integer field is missing: {field or key}")
	return _non_negative_integer(container[key], field or key)


def _optional_integer(container: Mapping[str, Any], key: str, field: str | None = None) -> int:
	if key not in container or container[key] is None:
		return 0
	return _non_negative_integer(container[key], field or key)


def _boolean_field(container: Mapping[str, Any], key: str, field: str | None = None) -> bool:
	value = container.get(key)
	if type(value) is not bool:
		raise ArchiveContractError(f"Expected boolean field: {field or key}")
	return value


def _positive_unique_revisions(value: object, field: str) -> list[int]:
	if not isinstance(value, list):
		raise ArchiveContractError(f"Expected revision list: {field}")
	result: list[int] = []
	seen: set[int] = set()
	for revision in value:
		if type(revision) is not int or revision <= 0 or revision in seen:
			raise ArchiveContractError(f"Invalid or duplicate revision in {field}: {revision!r}")
		seen.add(revision)
		result.append(revision)
	return result


def _string_list(value: object, field: str) -> list[str]:
	if not isinstance(value, list):
		raise ArchiveContractError(f"Expected string list: {field}")
	result: list[str] = []
	for item in value:
		if not isinstance(item, str) or not item.strip():
			raise ArchiveContractError(f"Invalid string item in {field}: {item!r}")
		result.append(item.strip())
	return result


def _safe_filename(value: object, field: str) -> str:
	if not isinstance(value, str) or not value.strip():
		raise ArchiveContractError(f"Required filename is missing: {field}")
	filename = value.strip()
	if filename in {".", ".."} or any(char in filename for char in ("/", "\\", ":", "\r", "\n", "\x00")):
		raise ArchiveContractError(f"Expected a plain filename: {field}")
	return filename


def _hash_value(value: object, field: str, pattern: re.Pattern[str]) -> str:
	if not isinstance(value, str) or not pattern.fullmatch(value):
		raise ArchiveContractError(f"Invalid hash field: {field}")
	return value


def _created_at(value: object) -> str:
	if not isinstance(value, str) or not value.strip():
		raise ArchiveContractError("Required text field is missing: created_at")
	text = value.strip()
	try:
		parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
	except ValueError as error:
		raise ArchiveContractError("created_at must be an ISO-8601 date-time") from error
	if parsed.tzinfo is None:
		raise ArchiveContractError("created_at must include a timezone")
	return text


def _safe_fixed_path(value: object, field: str) -> str:
	if not isinstance(value, str) or not value.startswith("/") or "\\" in value or "\x00" in value:
		raise ArchiveContractError(f"Expected normalized archive path: {field}")
	return value


def _copy_check_detail(value: object, field: str) -> object:
	if isinstance(value, Mapping):
		result: dict[str, object] = {}
		for key, item in value.items():
			if not isinstance(key, str) or key in CHECK_DETAIL_DENIED_KEYS:
				continue
			result[key] = _copy_check_detail(item, f"{field}.{key}")
		return result
	if isinstance(value, list):
		return [
			_copy_check_detail(item, f"{field}[{index}]") for index, item in enumerate(value)
		]
	if value is None or isinstance(value, (str, bool, int, float)):
		return value
	raise ArchiveContractError(f"Unsupported value in check detail: {field}")


def _copy_check_entry(check_type: object, value: object) -> dict[str, object]:
	if not isinstance(check_type, str) or not check_type.strip():
		raise ArchiveContractError("Check entry type must be non-empty text")
	check = _mapping(value)
	items = check.get("items", [])
	warnings = check.get("warnings", [])
	if not isinstance(items, list) or not isinstance(warnings, list):
		raise ArchiveContractError(f"check entry items and warnings must be lists: {check_type}")

	from rules.registry import spec_for_type

	spec = spec_for_type(check_type)
	name = _optional_text(check, "name")
	if not name and spec is not None:
		name = str(spec.get("name") or "")
	tables: object = check.get("tables")
	if tables is None:
		tables = list(spec.get("tables") or []) if spec is not None else []
	return {
		"type": check_type,
		"name": name or check_type,
		"status": _required_text(check, "status", f"checks.{check_type}.status"),
		"item_count": _optional_integer(check, "item_count", f"checks.{check_type}.item_count"),
		"warning_count": _optional_integer(check, "warning_count", f"checks.{check_type}.warning_count"),
		"tables": _string_list(tables, f"checks.{check_type}.tables"),
		"items": [
			_copy_check_detail(item, f"checks.{check_type}.items")
			for item in items[:CHECK_DETAIL_LIST_LIMIT]
		],
		"warnings": [
			_copy_check_detail(warning, f"checks.{check_type}.warnings")
			for warning in warnings[:CHECK_DETAIL_LIST_LIMIT]
		],
	}


def _copy_commit_warning(value: object) -> dict[str, object]:
	warning = _mapping(value)
	result: dict[str, object] = {}
	for key in (
		"type",
		"level",
		"input_method",
		"module",
		"table_name",
		"readable_name",
		"directory",
		"file_name",
		"fixed_path",
	):
		text = _optional_text(warning, key)
		if text:
			result[key] = text
	message = _public_message(warning.get("message"))
	if message:
		result["message"] = message
	if "revisions" in warning:
		result["revisions"] = _positive_unique_revisions(warning["revisions"], "commit_warning.revisions")
	if "actions" in warning:
		result["actions"] = _string_list(warning["actions"], "commit_warning.actions")
	for key in ("last_external_revision", "current_max_revision"):
		if key in warning:
			value_int = warning[key]
			if type(value_int) is not int or value_int <= 0:
				raise ArchiveContractError(f"Expected positive revision: commit_warning.{key}")
			result[key] = value_int
	return result


def _copy_files(value: object) -> list[dict[str, object]]:
	if not isinstance(value, list):
		raise ArchiveContractError("Expected file list: files")
	result: list[dict[str, object]] = []
	for index, raw_file in enumerate(value):
		file_info = _mapping(raw_file)
		item: dict[str, object] = {
			"action": _required_text(file_info, "action", f"files[{index}].action"),
			"fixed_path": _safe_fixed_path(file_info.get("fixed_path"), f"files[{index}].fixed_path"),
			"archive_path": _safe_fixed_path(file_info.get("archive_path"), f"files[{index}].archive_path"),
			"status": _required_text(file_info, "status", f"files[{index}].status"),
		}
		if "local_exists" in file_info:
			item["local_exists"] = _boolean_field(file_info, "local_exists", f"files[{index}].local_exists")
		if "size" in file_info:
			item["size"] = _non_negative_integer(file_info["size"], f"files[{index}].size")
		mtime = _optional_text(file_info, "mtime")
		if mtime:
			item["mtime"] = mtime
		result.append(item)
	return result


def build_archive_record(report: Mapping[str, Any]) -> dict[str, object]:
	if not isinstance(report, Mapping):
		raise ArchiveContractError("Report must be a mapping")

	package_id = _required_text(report, "package_id")
	idempotency_key = _required_text(report, "idempotency_key")
	if not IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
		raise ArchiveContractError("Invalid idempotency_key for HTTP header")

	input_data = _mapping(report.get("input"))
	region_filter = _mapping(input_data.get("region_filter"))
	naming = _mapping(report.get("naming"))
	package = _mapping(report.get("package"))
	status = _mapping(report.get("status"))
	validation = _mapping(report.get("validation"))
	summary = _mapping(validation.get("summary"))
	rule_set = _mapping(validation.get("rule_set"))
	checks = _mapping(validation.get("checks"))
	commit_record = _mapping(checks.get("commit_record"))
	last_external = _mapping(commit_record.get("last_external"))
	current_package = _mapping(commit_record.get("current_package"))
	comparison = _mapping(commit_record.get("comparison"))
	statistics = _mapping(commit_record.get("statistics"))

	region_code = _required_text(naming, "region_code", "naming.region_code")
	if region_code not in REGION_CODES:
		raise ArchiveContractError(f"Unsupported region_code: {region_code}")
	package_version = _required_text(naming, "package_version", "naming.package_version")
	previous_revisions = _positive_unique_revisions(
		last_external.get("revisions", []), "previous_external_revisions"
	)
	current_revisions = _positive_unique_revisions(
		current_package.get("revisions", []), "current_revisions"
	)

	archive_name = _safe_filename(package.get("name"), "package.name")
	list_file = _safe_filename(package.get("list_file"), "list_file")
	md5_file = _safe_filename(package.get("md5_file"), "md5_file")
	report_file = _safe_filename(package.get("report_file"), "report_file")
	file_count = _integer_field(package, "file_count")
	failed_count = _integer_field(package, "failed_count")
	skipped_count = _integer_field(package, "skipped_count")
	files = _copy_files(report.get("files"))
	if len(files) != file_count + failed_count + skipped_count:
		raise ArchiveContractError("Package counts do not match files list")

	warnings = commit_record.get("warnings", [])
	if not isinstance(warnings, list):
		raise ArchiveContractError("commit_record.warnings must be a list")
	whitelisted_paths = statistics.get("whitelisted_paths", [])
	if not isinstance(whitelisted_paths, list):
		raise ArchiveContractError("commit_record.whitelisted_paths must be a list")

	return {
		"schema_version": ARCHIVE_CONTRACT_VERSION,
		"record_type": ARCHIVE_RECORD_TYPE,
		"source_report_schema_version": _required_text(report, "schema_version"),
		"package_id": package_id,
		"idempotency_key": idempotency_key,
		"created_at": _created_at(report.get("created_at")),
		"release": {
			"region_code": region_code,
			"region_dir": _required_text(region_filter, "region_dir", "region_filter.region_dir"),
			"package_version": package_version,
			"previous_external_time": _optional_text(last_external, "time"),
			"previous_external_revision_spec": _optional_text(last_external, "revision_spec"),
			"previous_external_revisions": previous_revisions,
			"current_revision_spec": _optional_text(current_package, "revision_spec"),
			"current_revisions": current_revisions,
			"input_method": _optional_text(commit_record, "input_method"),
		},
		"package": {
			"name": archive_name,
			"md5": _hash_value(package.get("md5"), "package.md5", MD5_PATTERN),
			"sha256": _hash_value(package.get("sha256"), "package.sha256", SHA256_PATTERN),
			"file_count": file_count,
			"failed_count": failed_count,
			"skipped_count": skipped_count,
			"archive_root": _safe_fixed_path(input_data.get("archive_root"), "input.archive_root"),
			"artifacts": {
				"archive_file": archive_name,
				"list_file": list_file,
				"md5_file": md5_file,
				"report_file": report_file,
			},
		},
		"status": {
			"package_status": _required_text(status, "package_status", "status.package_status"),
			"validation_status": _required_text(status, "validation_status", "status.validation_status"),
		},
		"region_filter": {
			"enabled": _boolean_field(region_filter, "enabled", "region_filter.enabled"),
			"original_count": _integer_field(region_filter, "original_count", "region_filter.original_count"),
			"included_count": _integer_field(region_filter, "included_count", "region_filter.included_count"),
			"excluded_count": _integer_field(region_filter, "excluded_count", "region_filter.excluded_count"),
			"excluded_unknown_count": _integer_field(
				region_filter, "excluded_unknown_count", "region_filter.excluded_unknown_count"
			),
			"excluded_by_region": {
				str(key): _non_negative_integer(value, f"region_filter.excluded_by_region.{key}")
				for key, value in _mapping(region_filter.get("excluded_by_region")).items()
			},
		},
		"validation": {
			"rule_set": {
				"rule_set_id": _optional_text(rule_set, "rule_set_id") or "built-in",
				"version": _optional_text(rule_set, "version") or "1",
				"rule_hash": _optional_text(rule_set, "rule_hash") or "0" * 64,
				"published_at": _optional_text(rule_set, "published_at") or "1970-01-01T00:00:00Z",
				"region_code": _optional_text(rule_set, "region_code") or region_code,
				"source": _optional_text(rule_set, "source") or "built_in",
			},
			"summary": {
				"error_count": _integer_field(summary, "error_count", "validation.summary.error_count"),
				"warning_count": _integer_field(summary, "warning_count", "validation.summary.warning_count"),
				"confirm_count": _integer_field(summary, "confirm_count", "validation.summary.confirm_count"),
				"skipped_count": _integer_field(summary, "skipped_count", "validation.summary.skipped_count"),
			},
			"commit_record": {
				"status": _required_text(commit_record, "status", "commit_record.status"),
				"warning_count": _integer_field(commit_record, "warning_count", "commit_record.warning_count"),
				"package_path_count": _integer_field(
					current_package, "package_path_count", "commit_record.package_path_count"
				),
				"expected_revision_spec": _optional_text(comparison, "expected_revision_spec"),
				"included_revision_spec": _optional_text(comparison, "included_revision_spec"),
				"excluded_revision_spec": _optional_text(comparison, "excluded_revision_spec"),
				"scope_roots": _string_list(comparison.get("scope_roots", []), "commit_record.scope_roots"),
				"svn_log_returned_revision_count": _optional_integer(
					statistics, "svn_log_returned_revision_count", "commit_record.svn_log_returned_revision_count"
				),
				"svn_log_min_revision": _optional_integer(
					statistics, "svn_log_min_revision", "commit_record.svn_log_min_revision"
				),
				"svn_log_max_revision": _optional_integer(
					statistics, "svn_log_max_revision", "commit_record.svn_log_max_revision"
				),
				"filtered_unresolved_revision_count": _optional_integer(
					statistics,
					"filtered_unresolved_revision_count",
					"commit_record.filtered_unresolved_revision_count",
				),
				"whitelist_hit_count": _optional_integer(
					statistics, "whitelisted_warning_count", "commit_record.whitelist_hit_count"
				),
				"whitelisted_paths": [
					_safe_fixed_path(path, "commit_record.whitelisted_paths") for path in whitelisted_paths
				],
				"warnings": [_copy_commit_warning(warning) for warning in warnings],
			},
			"checks": [
				_copy_check_entry(check_type, check_value)
				for check_type, check_value in checks.items()
				if check_type != "commit_record"
			],
		},
		"files": files,
	}


def archive_create_headers(payload: Mapping[str, Any]) -> dict[str, str]:
	idempotency_key = _required_text(payload, "idempotency_key")
	if not IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
		raise ArchiveContractError("Invalid idempotency_key for HTTP header")
	return {
		"Content-Type": "application/json",
		"Idempotency-Key": idempotency_key,
		"X-AOV-Contract-Version": ARCHIVE_CONTRACT_VERSION,
	}
