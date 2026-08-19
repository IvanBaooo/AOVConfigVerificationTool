from __future__ import annotations

from typing import Dict, Optional

from package_naming import extract_timestamp_from_base_name, infer_package_name_info, rename_pack_result
from packer_core import LogCallback, PackResult, pack_incremental_package
from packer_mvp_optimized import apply_optimized_validation_to_report


def pack_incremental_package_mvp_region_name_only(
	*,
	svn_text: str,
	local_root: str,
	output_parent: str,
	validation_config: Optional[Dict[str, object]] = None,
	log: Optional[LogCallback] = None,
) -> PackResult:
	result = pack_incremental_package(
		svn_text=svn_text,
		local_root=local_root,
		output_parent=output_parent,
		log=log,
	)
	result.report.setdefault("input", {})
	if isinstance(result.report["input"], dict):
		result.report["input"]["package_region_usage"] = "name_only"  # type: ignore[index]
		result.report["input"]["package_content_source"] = "revision_and_svn_target"  # type: ignore[index]

	timestamp = extract_timestamp_from_base_name(result.base_name)
	name_info = infer_package_name_info(
		svn_text=svn_text,
		validation_config=validation_config,
		fallback_timestamp=timestamp,
	)
	result = rename_pack_result(result, name_info)
	if log:
		log(f"归档包命名：{result.base_name}", "info")
	return apply_optimized_validation_to_report(
		result=result,
		local_root=local_root,
		svn_text=svn_text,
		validation_config=validation_config,
		log=log,
	)
