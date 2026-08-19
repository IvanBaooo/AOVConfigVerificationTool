from __future__ import annotations

from collections.abc import Mapping
from typing import Any


ARCHIVE_CONTRACT_VERSION = "1.0"
ARCHIVE_RECORD_TYPE = "aov_package_archive"


class ArchivePayloadError(ValueError):
	pass


def _mapping(value: object) -> Mapping[str, Any]:
	return value if isinstance(value, Mapping) else {}


def _string(value: object) -> str:
	return value.strip() if isinstance(value, str) else ""


def _integer(value: object) -> int:
	try:
		return int(value or 0)
	except (TypeError, ValueError):
		return 0


def _boolean(value: object) -> bool:
	return value if isinstance(value, bool) else False


def _string_list(value: object) -> list[str]:
	if not isinstance(value, list):
		return []
	return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _integer_list(value: object) -> list[int]:
	if not isinstance(value, list):
		return []
	result: list[int] = []
	for item in value:
		try:
			result.append(int(item))
		except (TypeError, ValueError):
			continue
	return result


def _required_string(container: Mapping[str, Any], key: str) -> str:
	value = _string(container.get(key))
	if not value:
		raise ArchivePayloadError(f"Report field is required: {key}")
	return value


def _copy_string_mapping(value: object) -> dict[str, str]:
	return {
		str(key): item
		for key, item in _mapping(value).items()
		if isinstance(item, str)
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
		"message",
	):
		item = _string(warning.get(key))
		if item:
			result[key] = item
	revisions = _integer_list(warning.get("revisions"))
	if revisions:
		result["revisions"] = revisions
	actions = _string_list(warning.get("actions"))
	if actions:
		result["actions"] = actions
	for key in ("last_external_revision", "current_max_revision"):
		if key in warning:
			result[key] = _integer(warning.get(key))
	return result


def _copy_skin_warning(value: object) -> dict[str, object]:
	warning = _mapping(value)
	result: dict[str, object] = {}
	for key in ("type", "level", "id", "promo_id", "message"):
		item = _string(warning.get(key))
		if item:
			result[key] = item
	return result


def _copy_skin_promotion(value: object) -> dict[str, object]:
	promotion = _mapping(value)
	return {
		"promo_id": _string(promotion.get("promo_id")),
		"fields": _copy_string_mapping(promotion.get("fields")),
	}


def _copy_skin_item(value: object) -> dict[str, object]:
	item = _mapping(value)
	result: dict[str, object] = {}
	for key in (
		"type",
		"level",
		"module",
		"table",
		"main_sheet",
		"promo_sheet",
		"id",
		"hero_id",
		"hero_name",
		"skin_id",
		"skin_name",
	):
		text = _string(item.get(key))
		if text:
			result[key] = text
	match_reason = _mapping(item.get("match_reason"))
	if match_reason:
		result["match_reason"] = {
			"long_term_overlaps_window": _boolean(match_reason.get("long_term_overlaps_window")),
			"promotion_overlaps_window": _boolean(match_reason.get("promotion_overlaps_window")),
		}
	long_term_status = _copy_string_mapping(item.get("long_term_status"))
	if long_term_status:
		result["long_term_status"] = long_term_status
	promotions = item.get("promotions")
	if isinstance(promotions, list):
		result["promotions"] = [_copy_skin_promotion(promotion) for promotion in promotions]
	return result


def _copy_skin_precheck(value: object) -> dict[str, object]:
	check = _mapping(value)
	window = _mapping(check.get("check_window"))
	source = _mapping(check.get("source"))
	items = check.get("items")
	warnings = check.get("warnings")
	return {
		"status": _string(check.get("status")) or "not_run",
		"reason": _string(check.get("reason")),
		"check_window": {
			"start_time": _string(window.get("start_time")),
			"end_time": _string(window.get("end_time")),
		},
		"source": {
			"xml_exists": _boolean(source.get("xml_exists")),
			"main_sheet": _string(source.get("main_sheet")),
			"promo_sheet": _string(source.get("promo_sheet")),
		},
		"item_count": _integer(check.get("item_count")),
		"warning_count": _integer(check.get("warning_count")),
		"items": [_copy_skin_item(item) for item in items] if isinstance(items, list) else [],
		"warnings": [_copy_skin_warning(warning) for warning in warnings] if isinstance(warnings, list) else [],
	}


def _copy_files(value: object) -> list[dict[str, object]]:
	if not isinstance(value, list):
		return []
	result: list[dict[str, object]] = []
	for raw_file in value:
		file_info = _mapping(raw_file)
		item: dict[str, object] = {}
		for key in ("action", "fixed_path", "archive_path", "status", "mtime"):
			text = _string(file_info.get(key))
			if text:
				item[key] = text
		if isinstance(file_info.get("local_exists"), bool):
			item["local_exists"] = file_info["local_exists"]
		if "size" in file_info:
			item["size"] = _integer(file_info.get("size"))
		if item:
			result.append(item)
	return result


def build_archive_payload(report: Mapping[str, Any]) -> dict[str, object]:
	if not isinstance(report, Mapping):
		raise ArchivePayloadError("Report must be a mapping")

	package_id = _required_string(report, "package_id")
	idempotency_key = _required_string(report, "idempotency_key")
	created_at = _required_string(report, "created_at")
	source_report_schema_version = _required_string(report, "schema_version")

	input_data = _mapping(report.get("input"))
	region_filter = _mapping(input_data.get("region_filter"))
	naming = _mapping(report.get("naming"))
	package = _mapping(report.get("package"))
	status = _mapping(report.get("status"))
	validation = _mapping(report.get("validation"))
	validation_summary = _mapping(validation.get("summary"))
	rule_set = _mapping(validation.get("rule_set"))
	checks = _mapping(validation.get("checks"))
	commit_record = _mapping(checks.get("commit_record"))
	last_external = _mapping(commit_record.get("last_external"))
	current_package = _mapping(commit_record.get("current_package"))
	comparison = _mapping(commit_record.get("comparison"))
	statistics = _mapping(commit_record.get("statistics"))
	warnings = commit_record.get("warnings")

	region_code = _string(naming.get("region_code")) or _string(region_filter.get("region_code"))
	package_version = _string(naming.get("package_version"))
	if not region_code:
		raise ArchivePayloadError("Report field is required: naming.region_code")
	if not package_version:
		raise ArchivePayloadError("Report field is required: naming.package_version")

	package_name = _required_string(package, "name")
	package_md5 = _required_string(package, "md5")
	package_sha256 = _required_string(package, "sha256")

	return {
		"schema_version": ARCHIVE_CONTRACT_VERSION,
		"record_type": ARCHIVE_RECORD_TYPE,
		"source_report_schema_version": source_report_schema_version,
		"package_id": package_id,
		"idempotency_key": idempotency_key,
		"created_at": created_at,
		"release": {
			"region_code": region_code,
			"region_dir": _string(region_filter.get("region_dir")),
			"package_version": package_version,
			"previous_external_time": _string(last_external.get("time")),
			"previous_external_revision_spec": _string(last_external.get("revision_spec")),
			"previous_external_revisions": _integer_list(last_external.get("revisions")),
			"current_revision_spec": _string(current_package.get("revision_spec")),
			"current_revisions": _integer_list(current_package.get("revisions")),
			"input_method": _string(commit_record.get("input_method")),
		},
		"package": {
			"name": package_name,
			"md5": package_md5,
			"sha256": package_sha256,
			"file_count": _integer(package.get("file_count")),
			"failed_count": _integer(package.get("failed_count")),
			"skipped_count": _integer(package.get("skipped_count")),
			"archive_root": _string(input_data.get("archive_root")),
			"artifacts": {
				"archive_file": package_name,
				"list_file": _string(package.get("list_file")),
				"md5_file": _string(package.get("md5_file")),
				"report_file": _string(package.get("report_file")),
			},
		},
		"status": {
			"package_status": _string(status.get("package_status")) or "unknown",
			"validation_status": _string(status.get("validation_status")) or "unknown",
			"ftp_status": _string(status.get("ftp_status")) or "not_started",
			"archive_status": _string(status.get("archive_status")) or "not_started",
			"mail_status": _string(status.get("mail_status")) or "not_required",
		},
		"region_filter": {
			"enabled": _boolean(region_filter.get("enabled")),
			"original_count": _integer(region_filter.get("original_count")),
			"included_count": _integer(region_filter.get("included_count")),
			"excluded_count": _integer(region_filter.get("excluded_count")),
			"excluded_unknown_count": _integer(region_filter.get("excluded_unknown_count")),
			"excluded_by_region": {
				str(key): _integer(value)
				for key, value in _mapping(region_filter.get("excluded_by_region")).items()
			},
		},
		"validation": {
			"rule_set": {
				"rule_set_id": _string(rule_set.get("rule_set_id")) or "built-in",
				"version": _string(rule_set.get("version")) or "1",
				"rule_hash": _string(rule_set.get("rule_hash")) or "0" * 64,
				"published_at": _string(rule_set.get("published_at")) or "1970-01-01T00:00:00Z",
				"region_code": _string(rule_set.get("region_code")) or region_code,
				"source": _string(rule_set.get("source")) or "built_in",
			},
			"summary": {
				"error_count": _integer(validation_summary.get("error_count")),
				"warning_count": _integer(validation_summary.get("warning_count")),
				"confirm_count": _integer(validation_summary.get("confirm_count")),
				"skipped_count": _integer(validation_summary.get("skipped_count")),
			},
			"commit_record": {
				"status": _string(commit_record.get("status")) or "not_run",
				"warning_count": _integer(commit_record.get("warning_count")),
				"package_path_count": _integer(current_package.get("package_path_count")),
				"expected_revision_spec": _string(comparison.get("expected_revision_spec")),
				"included_revision_spec": _string(comparison.get("included_revision_spec")),
				"excluded_revision_spec": _string(comparison.get("excluded_revision_spec")),
				"scope_roots": _string_list(comparison.get("scope_roots")),
				"svn_log_returned_revision_count": _integer(statistics.get("svn_log_returned_revision_count")),
				"svn_log_min_revision": _integer(statistics.get("svn_log_min_revision")),
				"svn_log_max_revision": _integer(statistics.get("svn_log_max_revision")),
				"filtered_unresolved_revision_count": _integer(statistics.get("filtered_unresolved_revision_count")),
				"whitelist_hit_count": _integer(statistics.get("whitelisted_warning_count")),
				"whitelisted_paths": _string_list(statistics.get("whitelisted_paths")),
				"warnings": [_copy_commit_warning(warning) for warning in warnings]
				if isinstance(warnings, list)
				else [],
			},
			"skin_precheck": _copy_skin_precheck(checks.get("skin_precheck")),
		},
		"files": _copy_files(report.get("files")),
	}


def archive_request_headers(payload: Mapping[str, Any]) -> dict[str, str]:
	idempotency_key = _required_string(payload, "idempotency_key")
	return {
		"Content-Type": "application/json",
		"Idempotency-Key": idempotency_key,
		"X-AOV-Contract-Version": ARCHIVE_CONTRACT_VERSION,
	}
