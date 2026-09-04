from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Mapping

from svn_path_policy import normalize_policy_path, parse_whitelist_patterns


RULE_SCHEMA_VERSION = "1.0"
SUPPORTED_REGIONS = ("TW", "TH", "VN", "ID")
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

SUPPORTED_CONTENT_CHECK_TYPES = (
	"skin_sale_window",
	"skin_sale_change_check",
	"hidden_item_listing",
	"expiry_time_cross_check",
	"package_completeness",
)
CHECK_SEVERITIES = ("warning", "error", "confirm")


class ValidationRuleSetError(ValueError):
	pass


def _text(value: object, field: str, *, maximum: int = 256) -> str:
	if not isinstance(value, str) or not value.strip():
		raise ValidationRuleSetError(f"{field} must be a non-empty string.")
	result = value.strip()
	if len(result) > maximum:
		raise ValidationRuleSetError(f"{field} exceeds {maximum} characters.")
	return result


def _optional_text(value: object, field: str, *, maximum: int = 1000) -> str:
	if value is None:
		return ""
	if not isinstance(value, str):
		raise ValidationRuleSetError(f"{field} must be a string.")
	result = value.strip()
	if len(result) > maximum:
		raise ValidationRuleSetError(f"{field} exceeds {maximum} characters.")
	return result


def _published_at(value: object) -> str:
	text = _text(value, "published_at", maximum=64)
	if not text.endswith("Z"):
		raise ValidationRuleSetError("published_at must be an RFC3339 UTC timestamp ending in Z.")
	try:
		parsed = datetime.fromisoformat(text[:-1] + "+00:00")
	except ValueError as error:
		raise ValidationRuleSetError("published_at must be a valid RFC3339 timestamp.") from error
	if parsed.utcoffset() is None or parsed.microsecond:
		raise ValidationRuleSetError("published_at must use UTC and second precision.")
	return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def _content_checks(value: object, field: str) -> list[dict[str, object]]:
	if value is None:
		return []
	if not isinstance(value, list):
		raise ValidationRuleSetError(f"{field} must be a list.")
	checks: list[dict[str, object]] = []
	seen_ids: set[str] = set()
	for index, item in enumerate(value):
		item_field = f"{field}[{index}]"
		if not isinstance(item, Mapping):
			raise ValidationRuleSetError(f"{item_field} must be an object.")
		allowed = {
			"id", "type", "enabled", "name", "dtxml_path", "main_sheet",
			"promotion_sheet", "trigger_paths", "params", "applies_to",
			"severity", "blocking", "source_incident", "verify",
		}
		if set(item) - allowed:
			raise ValidationRuleSetError(f"{item_field} contains unsupported fields.")
		check_id = _text(item.get("id"), f"{item_field}.id", maximum=64)
		if not IDENTIFIER_PATTERN.fullmatch(check_id):
			raise ValidationRuleSetError(f"{item_field}.id contains unsupported characters.")
		key = check_id.casefold()
		if key in seen_ids:
			raise ValidationRuleSetError(f"{field} contains duplicate check id: {check_id}")
		seen_ids.add(key)
		check_type = _text(item.get("type"), f"{item_field}.type", maximum=64)
		if check_type not in SUPPORTED_CONTENT_CHECK_TYPES:
			raise ValidationRuleSetError(f"{item_field}.type is unsupported: {check_type}")
		enabled = item.get("enabled", True)
		if not isinstance(enabled, bool):
			raise ValidationRuleSetError(f"{item_field}.enabled must be a boolean.")
		requires_dtxml = check_type == "skin_sale_window"
		dtxml_value = item.get("dtxml_path")
		if requires_dtxml:
			dtxml_path = normalize_policy_path(
				_text(dtxml_value, f"{item_field}.dtxml_path", maximum=512)
			)
		elif dtxml_value is None or (isinstance(dtxml_value, str) and not dtxml_value.strip()):
			dtxml_path = ""
		else:
			dtxml_path = normalize_policy_path(
				_text(dtxml_value, f"{item_field}.dtxml_path", maximum=512)
			)
		if dtxml_path and (not dtxml_path.endswith(".dtxml") or "/../" in f"{dtxml_path}/"):
			raise ValidationRuleSetError(f"{item_field}.dtxml_path must identify a safe .dtxml file.")
		trigger_value = item.get("trigger_paths", [])
		if not isinstance(trigger_value, list) or not trigger_value or not all(isinstance(path, str) for path in trigger_value):
			raise ValidationRuleSetError(f"{item_field}.trigger_paths must be a non-empty string list.")
		trigger_paths: list[str] = []
		seen_triggers: set[str] = set()
		for trigger_index, trigger in enumerate(trigger_value):
			normalized = normalize_policy_path(
				_text(trigger, f"{item_field}.trigger_paths[{trigger_index}]", maximum=512)
			)
			if "/../" in f"{normalized}/":
				raise ValidationRuleSetError(f"{item_field}.trigger_paths contains an unsafe path.")
			trigger_key = normalized.casefold()
			if trigger_key not in seen_triggers:
				seen_triggers.add(trigger_key)
				trigger_paths.append(normalized)
		if requires_dtxml:
			main_sheet = _text(item.get("main_sheet"), f"{item_field}.main_sheet")
			promotion_sheet = _text(item.get("promotion_sheet"), f"{item_field}.promotion_sheet")
		else:
			main_sheet = _optional_text(item.get("main_sheet"), f"{item_field}.main_sheet")
			promotion_sheet = _optional_text(item.get("promotion_sheet"), f"{item_field}.promotion_sheet")
		normalized: dict[str, object] = {
			"id": check_id,
			"type": check_type,
			"enabled": enabled,
			"name": _text(item.get("name"), f"{item_field}.name"),
			"trigger_paths": trigger_paths,
		}
		if dtxml_path:
			normalized["dtxml_path"] = dtxml_path
		if main_sheet:
			normalized["main_sheet"] = main_sheet
		if promotion_sheet:
			normalized["promotion_sheet"] = promotion_sheet
		params = item.get("params")
		if params is not None:
			if not isinstance(params, Mapping):
				raise ValidationRuleSetError(f"{item_field}.params must be an object.")
			normalized["params"] = dict(params)
		applies_to = item.get("applies_to")
		if applies_to is not None:
			normalized["applies_to"] = _text(applies_to, f"{item_field}.applies_to", maximum=128)
		severity = item.get("severity")
		if severity is not None:
			severity_text = _text(severity, f"{item_field}.severity", maximum=16)
			if severity_text not in CHECK_SEVERITIES:
				raise ValidationRuleSetError(f"{item_field}.severity is unsupported: {severity_text}")
			normalized["severity"] = severity_text
		blocking = item.get("blocking")
		if blocking is not None:
			if not isinstance(blocking, bool):
				raise ValidationRuleSetError(f"{item_field}.blocking must be a boolean.")
			normalized["blocking"] = blocking
		source_incident = item.get("source_incident")
		if source_incident is not None:
			normalized["source_incident"] = _optional_text(source_incident, f"{item_field}.source_incident")
		verify = item.get("verify")
		if verify is not None:
			if not isinstance(verify, Mapping):
				raise ValidationRuleSetError(f"{item_field}.verify must be an object.")
			normalized["verify"] = dict(verify)
		checks.append(normalized)
	return checks

def _rules(value: object, field: str) -> dict[str, object]:
	if value is None:
		value = {}
	if not isinstance(value, Mapping):
		raise ValidationRuleSetError(f"{field} must be an object.")
	unknown = set(value) - {"path_mappings", "whitelist_paths", "content_checks"}
	if unknown:
		raise ValidationRuleSetError(f"{field} contains unsupported fields: {sorted(unknown)}")

	path_mappings_value = value.get("path_mappings", [])
	if not isinstance(path_mappings_value, list):
		raise ValidationRuleSetError(f"{field}.path_mappings must be a list.")
	path_mappings: list[dict[str, str]] = []
	seen_paths: set[str] = set()
	for index, item in enumerate(path_mappings_value):
		item_field = f"{field}.path_mappings[{index}]"
		if not isinstance(item, Mapping):
			raise ValidationRuleSetError(f"{item_field} must be an object.")
		if set(item) - {"path_suffix", "module", "table_name"}:
			raise ValidationRuleSetError(f"{item_field} contains unsupported fields.")
		path_suffix = normalize_policy_path(_text(item.get("path_suffix"), f"{item_field}.path_suffix"))
		if not path_suffix or path_suffix.endswith("/"):
			raise ValidationRuleSetError(f"{item_field}.path_suffix must identify a file.")
		table_name = _text(item.get("table_name"), f"{item_field}.table_name")
		module = _optional_text(item.get("module"), f"{item_field}.module", maximum=128)
		key = path_suffix.casefold()
		if key in seen_paths:
			raise ValidationRuleSetError(f"{field} contains duplicate path mapping: {path_suffix}")
		seen_paths.add(key)
		path_mappings.append({
			"path_suffix": path_suffix,
			"module": module,
			"table_name": table_name,
		})

	whitelist_value = value.get("whitelist_paths", [])
	if not isinstance(whitelist_value, list) or not all(isinstance(item, str) for item in whitelist_value):
		raise ValidationRuleSetError(f"{field}.whitelist_paths must be a string list.")
	whitelist_paths = parse_whitelist_patterns(whitelist_value)
	result: dict[str, object] = {
		"path_mappings": path_mappings,
		"whitelist_paths": whitelist_paths,
	}
	if "content_checks" in value:
		result["content_checks"] = _content_checks(value.get("content_checks"), f"{field}.content_checks")
	return result


def validate_rule_set(value: object) -> dict[str, object]:
	if not isinstance(value, Mapping):
		raise ValidationRuleSetError("Rule set must be an object.")
	unknown = set(value) - {
		"schema_version",
		"rule_set_id",
		"version",
		"published_at",
		"notes",
		"common",
		"regions",
	}
	if unknown:
		raise ValidationRuleSetError(f"Rule set contains unsupported fields: {sorted(unknown)}")
	if value.get("schema_version") != RULE_SCHEMA_VERSION:
		raise ValidationRuleSetError(f"schema_version must be {RULE_SCHEMA_VERSION}.")

	rule_set_id = _text(value.get("rule_set_id"), "rule_set_id", maximum=64)
	version = _text(value.get("version"), "version", maximum=64)
	if not IDENTIFIER_PATTERN.fullmatch(rule_set_id):
		raise ValidationRuleSetError("rule_set_id contains unsupported characters.")
	if not IDENTIFIER_PATTERN.fullmatch(version):
		raise ValidationRuleSetError("version contains unsupported characters.")

	regions_value = value.get("regions", {})
	if not isinstance(regions_value, Mapping):
		raise ValidationRuleSetError("regions must be an object.")
	unknown_regions = set(regions_value) - set(SUPPORTED_REGIONS)
	if unknown_regions:
		raise ValidationRuleSetError(f"Unsupported regions: {sorted(unknown_regions)}")
	regions = {
		region: _rules(regions_value.get(region), f"regions.{region}")
		for region in SUPPORTED_REGIONS
		if region in regions_value
	}
	return {
		"schema_version": RULE_SCHEMA_VERSION,
		"rule_set_id": rule_set_id,
		"version": version,
		"published_at": _published_at(value.get("published_at")),
		"notes": _optional_text(value.get("notes"), "notes"),
		"common": _rules(value.get("common"), "common"),
		"regions": regions,
	}


def canonical_rule_json(value: Mapping[str, object]) -> str:
	return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def rule_sha256(value: Mapping[str, object]) -> str:
	return hashlib.sha256(canonical_rule_json(value).encode("utf-8")).hexdigest()


def effective_rule_set(rule_set: Mapping[str, object], region_code: str) -> dict[str, object]:
	region = region_code.strip().upper()
	if region not in SUPPORTED_REGIONS:
		raise ValidationRuleSetError(f"Unsupported region_code: {region_code}")
	validated = validate_rule_set(rule_set)
	common = validated["common"]
	regions = validated["regions"]
	assert isinstance(common, dict)
	assert isinstance(regions, dict)
	regional = regions.get(region, {})
	assert isinstance(regional, dict)

	mappings: list[dict[str, str]] = []
	mapping_indexes: dict[str, int] = {}
	for source in (common.get("path_mappings", []), regional.get("path_mappings", [])):
		assert isinstance(source, list)
		for mapping in source:
			assert isinstance(mapping, dict)
			key = str(mapping["path_suffix"]).casefold()
			if key in mapping_indexes:
				mappings[mapping_indexes[key]] = dict(mapping)
			else:
				mapping_indexes[key] = len(mappings)
				mappings.append(dict(mapping))

	whitelist = parse_whitelist_patterns([
		*common.get("whitelist_paths", []),
		*regional.get("whitelist_paths", []),
	])
	content_checks: list[dict[str, object]] = []
	content_indexes: dict[str, int] = {}
	for source in (common.get("content_checks", []), regional.get("content_checks", [])):
		assert isinstance(source, list)
		for check in source:
			assert isinstance(check, dict)
			key = str(check["id"]).casefold()
			if key in content_indexes:
				content_checks[content_indexes[key]] = dict(check)
			else:
				content_indexes[key] = len(content_checks)
				content_checks.append(dict(check))
	effective_rules: dict[str, object] = {
		"path_mappings": mappings,
		"whitelist_paths": whitelist,
	}
	if content_checks or "content_checks" in common or "content_checks" in regional:
		effective_rules["content_checks"] = content_checks
	effective: dict[str, object] = {
		"schema_version": RULE_SCHEMA_VERSION,
		"rule_set_id": validated["rule_set_id"],
		"version": validated["version"],
		"published_at": validated["published_at"],
		"notes": validated["notes"],
		"region_code": region,
		"rules": effective_rules,
	}
	effective["rule_hash"] = rule_sha256(effective)
	return effective


def validate_effective_rule_set(value: object) -> dict[str, object]:
	if not isinstance(value, Mapping):
		raise ValidationRuleSetError("Effective rule set must be an object.")
	expected_keys = {
		"schema_version",
		"rule_set_id",
		"version",
		"published_at",
		"notes",
		"region_code",
		"rules",
		"rule_hash",
	}
	if set(value) != expected_keys:
		raise ValidationRuleSetError("Effective rule set fields do not match the contract.")
	region = _text(value.get("region_code"), "region_code", maximum=2).upper()
	if region not in SUPPORTED_REGIONS:
		raise ValidationRuleSetError(f"Unsupported region_code: {region}")
	rules = _rules(value.get("rules"), "rules")
	normalized: dict[str, object] = {
		"schema_version": RULE_SCHEMA_VERSION,
		"rule_set_id": _text(value.get("rule_set_id"), "rule_set_id", maximum=64),
		"version": _text(value.get("version"), "version", maximum=64),
		"published_at": _published_at(value.get("published_at")),
		"notes": _optional_text(value.get("notes"), "notes"),
		"region_code": region,
		"rules": rules,
	}
	expected_hash = rule_sha256(normalized)
	actual_hash = _text(value.get("rule_hash"), "rule_hash", maximum=64).lower()
	if not re.fullmatch(r"[0-9a-f]{64}", actual_hash) or actual_hash != expected_hash:
		raise ValidationRuleSetError("Effective rule set hash verification failed.")
	normalized["rule_hash"] = actual_hash
	return normalized
