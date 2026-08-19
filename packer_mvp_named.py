from __future__ import annotations

from typing import Dict, Optional

from package_naming import extract_timestamp_from_base_name, infer_package_name_info, rename_pack_result
from packer_core import LogCallback, PackResult, pack_incremental_package
from packer_mvp_optimized import apply_optimized_validation_to_report


def pack_incremental_package_mvp_named(
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
