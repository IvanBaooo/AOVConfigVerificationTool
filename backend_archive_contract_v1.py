from __future__ import annotations

import re
from datetime import datetime
from collections.abc import Mapping
from typing import Any

from backend_archive_contract import (
	ARCHIVE_CONTRACT_VERSION,
	ARCHIVE_RECORD_TYPE,
	ArchiveContractError,
	archive_create_headers as _archive_create_headers,
	build_archive_record as _build_archive_record,
)


SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"(?i)(?:\\|[a-z]:/+|(?<!:)//)")
WEB_URL_PATTERN = re.compile(r"(?i)https?://")
RFC3339_DATE_TIME_PATTERN = re.compile(
	r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
WINDOWS_INVALID_FILENAME_CHARS = frozenset('<>:"/\\|?*')
WINDOWS_RESERVED_NAMES = frozenset(
	{"CON", "PRN", "AUX", "NUL"}
	| {f"COM{number}" for number in range(1, 10)}
	| {f"LPT{number}" for number in range(1, 10)}
)

KNOWN_REGION_DIRS = frozenset(
	{
		"Taiwan",
		"Thailand",
		"Vietnam",
		"Vietnam_EXP",
		"Indonesia",
		"Bangladesh",
		"Brazil",
		"CHS_Standard_Global",
		"China_Exp",
		"ES",
		"Egypt",
		"India",
		"Japan",
		"Korea",
		"Mexico",
		"Russia",
		"Turkey",
		"United_Kingdom",
		"United_States",
	}
)


def _mapping(value: object, field: str) -> Mapping[str, Any]:
	if not isinstance(value, Mapping):
		raise ArchiveContractError(f"Expected mapping: {field}")
	return value


def _reported_count(container: Mapping[str, Any], key: str) -> int:
	value = container.get(key)
	if type(value) is not int or value < 0:
		raise ArchiveContractError(f"Expected non-negative integer: package.{key}")
	return value


def _validate_report_counts(report: Mapping[str, Any]) -> None:
	package = _mapping(report.get("package"), "package")
	files = report.get("files")
	if not isinstance(files, list):
		raise ArchiveContractError("Expected file list: files")

	packaged_count = 0
	failed_count = 0
	skipped_count = 0
	for index, item in enumerate(files):
		file_info = _mapping(item, f"files[{index}]")
		status = file_info.get("status")
		if status == "packaged":
			packaged_count += 1
		elif status in {"missing", "add_failed"}:
			failed_count += 1
		elif status == "deleted_skipped":
			skipped_count += 1
		else:
			raise ArchiveContractError(f"Unsupported package file status: files[{index}].status")

	expected = {
		"file_count": packaged_count,
		"failed_count": failed_count,
		"skipped_count": skipped_count,
	}
	for key, derived_value in expected.items():
		reported_value = _reported_count(package, key)
		if reported_value != derived_value:
			raise ArchiveContractError(
				f"Report count mismatch: package.{key}={reported_value}, files-derived={derived_value}"
			)


def _validate_rfc3339_datetime(value: object, field: str) -> None:
	if not isinstance(value, str) or not RFC3339_DATE_TIME_PATTERN.fullmatch(value):
		raise ArchiveContractError(f"Expected RFC 3339 date-time: {field}")
	try:
		normalized = value[:-1] + "+00:00" if value[-1] in {"Z", "z"} else value
		datetime.fromisoformat(normalized)
	except ValueError as exc:
		raise ArchiveContractError(f"Expected RFC 3339 date-time: {field}") from exc


def _validate_plain_filename(value: object, field: str) -> None:
	if not isinstance(value, str) or not value:
		raise ArchiveContractError(f"Required filename is missing: {field}")
	if value[-1] in {" ", "."}:
		raise ArchiveContractError(f"Windows-unsafe filename: {field}")
	if any(character in WINDOWS_INVALID_FILENAME_CHARS or ord(character) < 32 for character in value):
		raise ArchiveContractError(f"Windows-unsafe filename: {field}")
	stem = value.split(".", 1)[0].upper()
	if stem in WINDOWS_RESERVED_NAMES:
		raise ArchiveContractError(f"Windows-reserved filename: {field}")


def _validate_fixed_path(value: object, field: str) -> None:
	if not isinstance(value, str) or not value.startswith("/"):
		raise ArchiveContractError(f"Expected normalized fixed path: {field}")
	if "\\" in value or ":" in value or "\x00" in value:
		raise ArchiveContractError(f"Unsafe fixed path: {field}")

	segments = value[1:].split("/")
	if value != "/" and any(segment in {"", ".", ".."} for segment in segments):
		raise ArchiveContractError(f"Non-normalized fixed path: {field}")


def _validate_no_local_paths(value: object, field: str = "payload") -> None:
	if isinstance(value, str):
		if WINDOWS_ABSOLUTE_PATH_PATTERN.search(WEB_URL_PATTERN.sub("", value)):
			raise ArchiveContractError(f"Local absolute path is not allowed: {field}")
		return
	if isinstance(value, Mapping):
		for key, item in value.items():
			key_text = str(key)
			if WINDOWS_ABSOLUTE_PATH_PATTERN.search(key_text):
				raise ArchiveContractError(f"Local absolute path key is not allowed: {field}")
			_validate_no_local_paths(item, f"{field}.{key_text}")
		return
	if isinstance(value, list):
		for index, item in enumerate(value):
			_validate_no_local_paths(item, f"{field}[{index}]")


def _validate_final_payload(payload: Mapping[str, Any]) -> None:
	package_id = payload.get("package_id")
	if (
		not isinstance(package_id, str)
		or package_id in {".", ".."}
		or not SAFE_ID_PATTERN.fullmatch(package_id)
	):
		raise ArchiveContractError("Invalid package_id")

	_validate_rfc3339_datetime(payload.get("created_at"), "payload.created_at")

	package = _mapping(payload.get("package"), "payload.package")
	_validate_fixed_path(package.get("archive_root"), "package.archive_root")
	artifacts = _mapping(package.get("artifacts"), "payload.package.artifacts")
	_validate_plain_filename(package.get("name"), "package.name")
	for key in ("archive_file", "list_file", "md5_file", "report_file"):
		_validate_plain_filename(artifacts.get(key), f"package.artifacts.{key}")

	status = _mapping(payload.get("status"), "payload.status")
	expected_status_keys = {"package_status", "validation_status"}
	if set(status) != expected_status_keys or any(
		not isinstance(status[key], str) or not status[key] for key in expected_status_keys
	):
		raise ArchiveContractError("Mutable or invalid status fields are not allowed")

	region_filter = _mapping(payload.get("region_filter"), "payload.region_filter")
	excluded_by_region = _mapping(
		region_filter.get("excluded_by_region"), "payload.region_filter.excluded_by_region"
	)
	unknown_regions = set(excluded_by_region) - KNOWN_REGION_DIRS
	if unknown_regions:
		raise ArchiveContractError(f"Unknown region directory keys: {sorted(unknown_regions)}")

	validation = _mapping(payload.get("validation"), "payload.validation")
	rule_set = _mapping(validation.get("rule_set"), "payload.validation.rule_set")
	for key in ("rule_set_id", "version"):
		value = rule_set.get(key)
		if not isinstance(value, str) or not SAFE_ID_PATTERN.fullmatch(value):
			raise ArchiveContractError(f"Invalid validation rule metadata: {key}")
	rule_hash = rule_set.get("rule_hash")
	if not isinstance(rule_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", rule_hash):
		raise ArchiveContractError("Invalid validation rule metadata: rule_hash")
	_validate_rfc3339_datetime(rule_set.get("published_at"), "validation.rule_set.published_at")
	if rule_set.get("region_code") not in {"TW", "TH", "VN", "ID"}:
		raise ArchiveContractError("Invalid validation rule metadata: region_code")
	if rule_set.get("source") not in {"remote", "local_cache", "built_in"}:
		raise ArchiveContractError("Invalid validation rule metadata: source")
	commit_record = _mapping(validation.get("commit_record"), "payload.validation.commit_record")
	for index, scope_root in enumerate(commit_record.get("scope_roots", [])):
		_validate_fixed_path(scope_root, f"commit_record.scope_roots[{index}]")
	for index, fixed_path in enumerate(commit_record.get("whitelisted_paths", [])):
		_validate_fixed_path(fixed_path, f"commit_record.whitelisted_paths[{index}]")
	for index, warning in enumerate(commit_record.get("warnings", [])):
		warning_data = _mapping(warning, f"commit_record.warnings[{index}]")
		if warning_data.get("fixed_path"):
			_validate_fixed_path(warning_data["fixed_path"], f"commit_record.warnings[{index}].fixed_path")

	checks = validation.get("checks")
	if not isinstance(checks, list):
		raise ArchiveContractError("Expected check entry list: validation.checks")
	for index, entry in enumerate(checks):
		entry_data = _mapping(entry, f"validation.checks[{index}]")
		entry_type = entry_data.get("type")
		if not isinstance(entry_type, str) or not SAFE_ID_PATTERN.fullmatch(entry_type):
			raise ArchiveContractError(f"Invalid check entry type: validation.checks[{index}].type")
		if entry_data.get("status") not in {"passed", "warning", "error", "confirm", "skipped"}:
			raise ArchiveContractError(f"Invalid check entry status: validation.checks[{index}].status")
		for key in ("item_count", "warning_count"):
			value = entry_data.get(key)
			if type(value) is not int or value < 0:
				raise ArchiveContractError(
					f"Expected non-negative integer: validation.checks[{index}].{key}"
				)
		tables = entry_data.get("tables")
		if not isinstance(tables, list) or any(not isinstance(table, str) for table in tables):
			raise ArchiveContractError(f"Expected string list: validation.checks[{index}].tables")

	for index, item in enumerate(payload.get("files", [])):
		file_info = _mapping(item, f"payload.files[{index}]")
		_validate_fixed_path(file_info.get("fixed_path"), f"files[{index}].fixed_path")
		_validate_fixed_path(file_info.get("archive_path"), f"files[{index}].archive_path")

	_validate_no_local_paths(payload)


def build_archive_record(report: Mapping[str, Any]) -> dict[str, object]:
	if not isinstance(report, Mapping):
		raise ArchiveContractError("Report must be a mapping")
	_validate_report_counts(report)
	payload = _build_archive_record(report)
	_validate_final_payload(payload)
	return payload


def archive_create_headers(payload: Mapping[str, Any]) -> dict[str, str]:
	_validate_final_payload(payload)
	return _archive_create_headers(payload)


__all__ = [
	"ARCHIVE_CONTRACT_VERSION",
	"ARCHIVE_RECORD_TYPE",
	"ArchiveContractError",
	"archive_create_headers",
	"build_archive_record",
]
