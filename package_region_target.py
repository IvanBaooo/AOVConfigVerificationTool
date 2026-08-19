from __future__ import annotations

from package_region_filter import region_dir_for_code
from project_defaults import SERVERBYTES_SVN_URL


def svn_target_for_region(region_code: str) -> str:
	if not SERVERBYTES_SVN_URL:
		return ""
	region_dir = region_dir_for_code(region_code)
	if not region_dir:
		return SERVERBYTES_SVN_URL
	return f"{SERVERBYTES_SVN_URL}/{region_dir}"


def scope_root_for_region(region_code: str) -> str:
	region_dir = region_dir_for_code(region_code)
	return f"/{region_dir}" if region_dir else ""
