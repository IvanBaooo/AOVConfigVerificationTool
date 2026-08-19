from __future__ import annotations

import fnmatch
import os
import re
from typing import Dict, Iterable, List, Mapping, Sequence


DEFAULT_TABLE_MAPPINGS: Sequence[Mapping[str, str]] = (
	{
		"path_suffix": "/Databin/Server/Shop/SvrHeroSkinShop.xml",
		"module": "皮肤",
		"table_name": "英雄皮肤促销表",
	},
	{
		"path_suffix": "/Databin/Server/Shop/SvrHeroSkinShop.bytes",
		"module": "皮肤",
		"table_name": "英雄皮肤促销表",
	},
)


def normalize_policy_path(path: str) -> str:
	value = (path or "").strip().strip('"').replace("\\", "/")
	value = re.sub(r"\s+\(from\s+.+\)$", "", value).strip()
	match = re.search(r"(?:^|/)ServerBytes(/.*)$", value, flags=re.IGNORECASE)
	if match:
		value = match.group(1)
	if value and not value.startswith("/"):
		value = "/" + value
	while "//" in value:
		value = value.replace("//", "/")
	return value


def describe_svn_path(
	fixed_path: str,
	extra_mappings: Iterable[Mapping[str, object]] = (),
) -> Dict[str, str]:
	normalized = normalize_policy_path(fixed_path)
	file_name = os.path.basename(normalized)
	directory = os.path.dirname(normalized).replace("\\", "/")

	for mapping in (*tuple(extra_mappings), *DEFAULT_TABLE_MAPPINGS):
		suffix = normalize_policy_path(str(mapping.get("path_suffix") or mapping.get("path") or ""))
		if suffix and normalized.casefold().endswith(suffix.casefold()):
			table_name = str(mapping.get("table_name") or "").strip() or os.path.splitext(file_name)[0]
			module = str(mapping.get("module") or "").strip()
			return {
				"module": module,
				"table_name": table_name,
				"readable_name": f"{table_name} / {file_name}" if file_name else table_name,
				"directory": directory,
				"file_name": file_name,
				"fixed_path": normalized,
				"mapping_source": "configured" if mapping not in DEFAULT_TABLE_MAPPINGS else "built_in",
			}

	table_name = os.path.splitext(file_name)[0] if file_name else ""
	return {
		"module": "",
		"table_name": table_name,
		"readable_name": f"{table_name} / {file_name}" if table_name and file_name else (file_name or normalized),
		"directory": directory,
		"file_name": file_name,
		"fixed_path": normalized,
		"mapping_source": "file_name",
	}


def parse_whitelist_patterns(value: object) -> List[str]:
	if isinstance(value, str):
		raw_items = re.split(r"[,;，；\n\r]+", value)
	elif isinstance(value, (list, tuple)):
		raw_items = [str(item) for item in value]
	else:
		return []

	patterns: List[str] = []
	for raw_item in raw_items:
		item = raw_item.strip()
		if not item or item.startswith("#"):
			continue
		normalized = normalize_policy_path(item)
		if normalized and normalized not in patterns:
			patterns.append(normalized)
	return patterns


def path_matches_whitelist(fixed_path: str, pattern: str) -> bool:
	path = normalize_policy_path(fixed_path)
	candidate = normalize_policy_path(pattern)
	if not path or not candidate:
		return False

	path_folded = path.casefold()
	candidate_folded = candidate.casefold()
	basename = os.path.basename(path_folded)
	candidate_basename = os.path.basename(candidate_folded)

	if any(char in candidate for char in "*?[]"):
		return (
			fnmatch.fnmatchcase(path_folded, candidate_folded)
			or fnmatch.fnmatchcase(basename, candidate_basename)
		)

	if candidate.endswith("/"):
		return path_folded.startswith(candidate_folded)
	if "/" not in pattern.replace("\\", "/").strip("/"):
		return basename == candidate_basename
	return path_folded == candidate_folded


def matching_whitelist_pattern(fixed_path: str, patterns: Iterable[str]) -> str:
	for pattern in patterns:
		if path_matches_whitelist(fixed_path, pattern):
			return pattern
	return ""
