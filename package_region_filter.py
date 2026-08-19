from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from packer_core import ParsedSvnEntry, parse_svn_entries


REGION_DIR_BY_CODE = {
	"TW": "Taiwan",
	"TH": "Thailand",
	"VN": "Vietnam",
	"ID": "Indonesia",
}

REGION_CODE_BY_DIR = {value.lower(): key for key, value in REGION_DIR_BY_CODE.items()}


@dataclass
class RegionFilterResult:
	filtered_svn_text: str
	enabled: bool
	region_code: str
	region_dir: str
	original_count: int
	included_count: int
	excluded_count: int
	excluded_by_region: Dict[str, int]
	excluded_unknown_count: int


def normalize_region_code(region_code: str) -> str:
	value = (region_code or "").strip().upper()
	if value in REGION_DIR_BY_CODE:
		return value
	lowered = (region_code or "").strip().lower()
	return REGION_CODE_BY_DIR.get(lowered, value)


def region_dir_for_code(region_code: str) -> str:
	code = normalize_region_code(region_code)
	return REGION_DIR_BY_CODE.get(code, "")


def _entry_region_dir(entry: ParsedSvnEntry) -> str:
	normalized = entry.fixed_path.replace("\\", "/").strip("/")
	if not normalized:
		return ""
	return normalized.split("/", 1)[0]


def _entry_to_packer_line(entry: ParsedSvnEntry) -> str:
	return f"{entry.action} ServerBytes{entry.fixed_path}"


def filter_svn_text_by_region(
	*,
	svn_text: str,
	region_code: str,
	enabled: bool = True,
) -> RegionFilterResult:
	entries = parse_svn_entries(svn_text)
	code = normalize_region_code(region_code)
	target_region_dir = region_dir_for_code(code)
	if not enabled or not target_region_dir:
		return RegionFilterResult(
			filtered_svn_text=svn_text,
			enabled=False,
			region_code=code,
			region_dir=target_region_dir,
			original_count=len(entries),
			included_count=len(entries),
			excluded_count=0,
			excluded_by_region={},
			excluded_unknown_count=0,
		)

	included: List[ParsedSvnEntry] = []
	excluded_by_region: Dict[str, int] = {}
	excluded_unknown_count = 0
	for entry in entries:
		entry_region = _entry_region_dir(entry)
		if entry_region.lower() == target_region_dir.lower():
			included.append(entry)
			continue
		if entry_region:
			excluded_by_region[entry_region] = excluded_by_region.get(entry_region, 0) + 1
		else:
			excluded_unknown_count += 1

	filtered_svn_text = "\n".join(_entry_to_packer_line(entry) for entry in included)
	return RegionFilterResult(
		filtered_svn_text=filtered_svn_text,
		enabled=True,
		region_code=code,
		region_dir=target_region_dir,
		original_count=len(entries),
		included_count=len(included),
		excluded_count=len(entries) - len(included),
		excluded_by_region=dict(sorted(excluded_by_region.items())),
		excluded_unknown_count=excluded_unknown_count,
	)


def region_filter_report(result: RegionFilterResult) -> Dict[str, object]:
	return {
		"enabled": result.enabled,
		"region_code": result.region_code,
		"region_dir": result.region_dir,
		"original_count": result.original_count,
		"included_count": result.included_count,
		"excluded_count": result.excluded_count,
		"excluded_by_region": result.excluded_by_region,
		"excluded_unknown_count": result.excluded_unknown_count,
	}
