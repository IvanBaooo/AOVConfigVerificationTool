from __future__ import annotations

import time
from typing import Dict, Optional

from package_naming import extract_timestamp_from_base_name, infer_package_name_info, rename_pack_result
from package_region_filter import filter_svn_text_by_region, region_filter_report
from packer_core import LogCallback, PackResult, PackagingError, pack_incremental_package
from packer_mvp_optimized import apply_optimized_validation_to_report


def _commit_config(validation_config: Optional[Dict[str, object]]) -> Dict[str, object]:
	if not validation_config:
		return {}
	value = validation_config.get("commit_record")
	if isinstance(value, dict):
		return value
	return {}


def _package_region_code(validation_config: Optional[Dict[str, object]]) -> str:
	config = validation_config or {}
	commit_config = _commit_config(validation_config)
	return str(
		config.get("package_region_code")
		or config.get("region_code")
		or commit_config.get("package_region_code")
		or ""
	).strip()


def _region_filter_enabled(validation_config: Optional[Dict[str, object]]) -> bool:
	config = validation_config or {}
	value = config.get("package_region_filter_enabled")
	if value is None:
		value = _commit_config(validation_config).get("package_region_filter_enabled")
	if value is None:
		return True
	return bool(value)


def pack_incremental_package_mvp_region_named(
	*,
	svn_text: str,
	local_root: str,
	output_parent: str,
	validation_config: Optional[Dict[str, object]] = None,
	log: Optional[LogCallback] = None,
) -> PackResult:
	package_started = time.perf_counter()
	region_code = _package_region_code(validation_config)
	filter_result = filter_svn_text_by_region(
		svn_text=svn_text,
		region_code=region_code,
		enabled=_region_filter_enabled(validation_config),
	)
	if filter_result.enabled:
		if log:
			log(
				"区域过滤："
				f"{filter_result.region_code}/{filter_result.region_dir} "
				f"保留 {filter_result.included_count} 条，排除 {filter_result.excluded_count} 条",
				"info",
			)
		if filter_result.included_count == 0:
			raise PackagingError(
				f"按区域 {filter_result.region_code}/{filter_result.region_dir} 过滤后没有可打包文件，请确认打包区域或 revision 输入。"
			)

	effective_svn_text = filter_result.filtered_svn_text
	result = pack_incremental_package(
		svn_text=effective_svn_text,
		local_root=local_root,
		output_parent=output_parent,
		log=log,
	)
	result.report.setdefault("input", {})
	if isinstance(result.report["input"], dict):
		result.report["input"]["region_filter"] = region_filter_report(filter_result)  # type: ignore[index]
		package_source = (validation_config or {}).get("package_source")
		if isinstance(package_source, dict):
			result.report["input"]["package_source"] = dict(package_source)  # type: ignore[index]

	timestamp = extract_timestamp_from_base_name(result.base_name)
	name_info = infer_package_name_info(
		svn_text=effective_svn_text,
		validation_config=validation_config,
		fallback_timestamp=timestamp,
	)
	result = rename_pack_result(result, name_info)
	performance = result.report.setdefault("performance", {})
	if isinstance(performance, dict):
		stages = performance.setdefault("stages", {})
		if isinstance(stages, dict):
			stages["archive_package"] = round(time.perf_counter() - package_started, 3)
	if log:
		log(f"归档包命名：{result.base_name}", "info")
	return apply_optimized_validation_to_report(
		result=result,
		local_root=local_root,
		svn_text=effective_svn_text,
		validation_config=validation_config,
		log=log,
	)
