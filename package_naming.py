from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

from packer_core import ParsedSvnEntry, parse_svn_entries


REGION_CODE_BY_DIR = {
	"taiwan": "TW",
	"thailand": "TH",
	"vietnam": "VN",
	"indonesia": "ID",
}


@dataclass
class PackageNameInfo:
	base_name: str
	region_code: str
	package_version: str
	timestamp: str
	region_source: str
	version_source: str


def sanitize_name_part(value: str, fallback: str) -> str:
	cleaned = re.sub(r"[^A-Za-z0-9_-]+", "", (value or "").strip())
	return cleaned or fallback


def extract_timestamp_from_base_name(base_name: str) -> str:
	match = re.search(r"(\d{14})$", base_name or "")
	if match:
		return match.group(1)
	return ""


def parse_package_version_from_svn_url(svn_url: str) -> str:
	match = re.search(r"(Beta\d+)", svn_url or "", flags=re.IGNORECASE)
	if not match:
		return ""
	value = match.group(1)
	return "Beta" + value[4:]


def _known_region_from_path(path: str) -> str:
	normalized = (path or "").replace("\\", "/").strip("/")
	if not normalized:
		return ""
	first_part = normalized.split("/", 1)[0].lower()
	return REGION_CODE_BY_DIR.get(first_part, "")


def infer_region_from_paths(fixed_paths: Iterable[str]) -> str:
	regions = sorted({region for region in (_known_region_from_path(path) for path in fixed_paths) if region})
	if len(regions) == 1:
		return regions[0]
	if len(regions) > 1:
		return "MIX"
	return ""


def infer_region_from_scope_roots(scope_roots: Sequence[str]) -> str:
	return infer_region_from_paths(scope_roots)


def _commit_config(validation_config: Optional[Dict[str, object]]) -> Dict[str, object]:
	if not validation_config:
		return {}
	value = validation_config.get("commit_record")
	if isinstance(value, dict):
		return value
	value = validation_config.get("commit_record_check")
	if isinstance(value, dict):
		return value
	return {}


def _string_list(value: object) -> List[str]:
	if isinstance(value, str):
		return [item.strip() for item in value.replace("；", ",").replace("，", ",").split(",") if item.strip()]
	if isinstance(value, list):
		return [str(item).strip() for item in value if str(item).strip()]
	return []


def infer_package_name_info(
	*,
	svn_text: str,
	validation_config: Optional[Dict[str, object]],
	fallback_timestamp: str,
) -> PackageNameInfo:
	config = validation_config or {}
	commit_config = _commit_config(validation_config)
	entries: List[ParsedSvnEntry] = parse_svn_entries(svn_text)
	fixed_paths = [entry.fixed_path for entry in entries]

	explicit_region = str(
		config.get("package_region_code")
		or config.get("region_code")
		or commit_config.get("package_region_code")
		or ""
	).strip()
	if explicit_region:
		region_code = sanitize_name_part(explicit_region.upper(), "UNK")
		region_source = "config"
	else:
		scope_region = infer_region_from_scope_roots(_string_list(commit_config.get("scope_roots")))
		if scope_region:
			region_code = scope_region
			region_source = "scope_roots"
		else:
			region_code = infer_region_from_paths(fixed_paths) or "UNK"
			region_source = "package_paths" if region_code != "UNK" else "fallback"

	explicit_version = str(config.get("package_version") or commit_config.get("package_version") or "").strip()
	if explicit_version:
		package_version = sanitize_name_part(explicit_version, "UNKNOWN")
		version_source = "config"
	else:
		svn_target = str(commit_config.get("svn_target") or config.get("svn_url") or "").strip()
		package_version = sanitize_name_part(parse_package_version_from_svn_url(svn_target), "UNKNOWN")
		version_source = "svn_target" if package_version != "UNKNOWN" else "fallback"

	timestamp = sanitize_name_part(fallback_timestamp, "00000000000000")
	base_name = f"sgame_{region_code}_{package_version}_{timestamp}"
	return PackageNameInfo(
		base_name=base_name,
		region_code=region_code,
		package_version=package_version,
		timestamp=timestamp,
		region_source=region_source,
		version_source=version_source,
	)


def rename_pack_result(result, name_info: PackageNameInfo):
	from packer_core import PackagingError

	if result.base_name == name_info.base_name:
		return result

	old_output_dir = result.output_dir
	output_parent = os.path.dirname(old_output_dir)
	new_output_dir = os.path.join(output_parent, name_info.base_name)
	if os.path.exists(new_output_dir):
		raise PackagingError(f"输出目录已存在，无法生成同名归档包：{new_output_dir}")

	old_tar_path = result.tar_path
	old_list_path = result.list_path
	old_md5_path = result.md5_path
	old_report_path = result.report_path

	new_tar_filename = f"{name_info.base_name}.tar.gz"
	new_list_filename = f"{name_info.base_name}.list.txt"
	new_md5_filename = f"{name_info.base_name}.md5.txt"
	new_report_filename = f"{name_info.base_name}.report.json"

	new_tar_path = os.path.join(old_output_dir, new_tar_filename)
	new_list_path = os.path.join(old_output_dir, new_list_filename)
	new_md5_path = os.path.join(old_output_dir, new_md5_filename)
	new_report_path = os.path.join(old_output_dir, new_report_filename)

	os.replace(old_tar_path, new_tar_path)
	os.replace(old_list_path, new_list_path)
	os.replace(old_md5_path, new_md5_path)
	os.replace(old_report_path, new_report_path)

	with open(new_md5_path, "w", encoding="utf-8") as f_md5:
		f_md5.write(f"{result.md5}  {new_tar_filename}\n")

	result.report["package_id"] = name_info.base_name
	result.report["idempotency_key"] = name_info.base_name
	result.report["naming"] = {
		"old_base_name": result.base_name,
		"base_name": name_info.base_name,
		"region_code": name_info.region_code,
		"region_source": name_info.region_source,
		"package_version": name_info.package_version,
		"version_source": name_info.version_source,
		"timestamp": name_info.timestamp,
	}
	package = result.report.get("package")
	if isinstance(package, dict):
		package["name"] = new_tar_filename
		package["list_file"] = new_list_filename
		package["md5_file"] = new_md5_filename
		package["report_file"] = new_report_filename

	with open(new_report_path, "w", encoding="utf-8") as f_report:
		import json

		json.dump(result.report, f_report, ensure_ascii=False, indent=2)
		f_report.write("\n")

	os.replace(old_output_dir, new_output_dir)

	result.base_name = name_info.base_name
	result.output_dir = new_output_dir
	result.tar_path = os.path.join(new_output_dir, new_tar_filename)
	result.list_path = os.path.join(new_output_dir, new_list_filename)
	result.md5_path = os.path.join(new_output_dir, new_md5_filename)
	result.report_path = os.path.join(new_output_dir, new_report_filename)
	return result
