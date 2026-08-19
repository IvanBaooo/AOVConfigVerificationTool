from __future__ import annotations

import os
import re
import xml.etree.ElementTree as XmlET
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from svn_path_policy import describe_svn_path


REGION_ROOTS = ("Taiwan", "Thailand", "Vietnam", "Indonesia")

@dataclass
class SvnChangedPath:
	action: str
	path: str
	fixed_path: str
	raw_line: str


@dataclass
class SvnRevisionChange:
	revision: int
	author: str = ""
	date: str = ""
	message: str = ""
	paths: List[SvnChangedPath] = field(default_factory=list)


class RevisionSpecError(ValueError):
	pass


def parse_revision_spec(spec: str) -> List[int]:
	"""Parse revision expressions such as r10001-r10005 or r10001,r10003."""
	spec = (spec or "").strip()
	if not spec:
		return []

	normalized = (
		spec.replace("，", ",")
		.replace("；", ";")
		.replace("、", ",")
		.replace("～", "~")
		.replace("—", "-")
		.replace("－", "-")
	)
	tokens = re.split(r"[,;\n]+", normalized)
	revisions: Set[int] = set()

	for raw_token in tokens:
		token = raw_token.strip()
		if not token:
			continue
		token = re.sub(r"\s*([:\-~])\s*", r"\1", token)
		if re.search(r"\s+", token):
			for sub_token in re.split(r"\s+", token):
				for revision in parse_revision_spec(sub_token):
					revisions.add(revision)
			continue

		range_match = re.match(r"^[rR]?(\d+)(?:-|:|~|至)[rR]?(\d+)$", token)
		if range_match:
			start = int(range_match.group(1))
			end = int(range_match.group(2))
			low, high = sorted((start, end))
			revisions.update(range(low, high + 1))
			continue

		single_match = re.match(r"^[rR]?(\d+)$", token)
		if single_match:
			revisions.add(int(single_match.group(1)))
			continue

		raise RevisionSpecError(f"Unsupported SVN revision spec token: {raw_token}")

	return sorted(revisions)


def summarize_revision_list(revisions: Sequence[int]) -> str:
	if not revisions:
		return ""
	ordered = sorted(set(revisions))
	ranges: List[str] = []
	start = ordered[0]
	previous = ordered[0]
	for revision in ordered[1:]:
		if revision == previous + 1:
			previous = revision
			continue
		ranges.append(f"r{start}" if start == previous else f"r{start}-r{previous}")
		start = previous = revision
	ranges.append(f"r{start}" if start == previous else f"r{start}-r{previous}")
	return ",".join(ranges)


def normalize_fixed_path(path: str) -> Optional[str]:
	"""Convert an SVN path to a ServerBytes-relative path beginning with '/'."""
	value = (path or "").strip().strip('"')
	if not value:
		return None
	value = re.sub(r"\s+\(from\s+.+\)$", "", value).strip()
	value = value.replace("\\", "/")

	match = re.search(r"(?:^|/)ServerBytes(/.*)$", value, flags=re.IGNORECASE)
	if match:
		fixed_path = match.group(1)
	else:
		stripped = value.lstrip("/")
		if not stripped.startswith(REGION_ROOTS):
			return None
		fixed_path = "/" + stripped

	while "//" in fixed_path:
		fixed_path = fixed_path.replace("//", "/")
	return fixed_path


def _parse_text_svn_log(log_text: str) -> List[SvnRevisionChange]:
	revisions: List[SvnRevisionChange] = []
	current: Optional[SvnRevisionChange] = None
	in_changed_paths = False

	for raw_line in log_text.splitlines():
		line = raw_line.rstrip("\n")
		header = re.match(r"^r(\d+)\s+\|\s*([^|]*)\|\s*([^|]*)(?:\|.*)?$", line.strip())
		if header:
			current = SvnRevisionChange(
				revision=int(header.group(1)),
				author=header.group(2).strip(),
				date=header.group(3).strip(),
			)
			revisions.append(current)
			in_changed_paths = False
			continue

		if current is None:
			continue

		if line.strip() == "Changed paths:":
			in_changed_paths = True
			continue

		if in_changed_paths:
			if not line.strip():
				in_changed_paths = False
				continue
			path_match = re.match(r"^\s*([AMDR])\s+(.+?)\s*$", line)
			if path_match:
				action = path_match.group(1)
				path = path_match.group(2).strip()
				fixed_path = normalize_fixed_path(path)
				if fixed_path:
					current.paths.append(
						SvnChangedPath(action=action, path=path, fixed_path=fixed_path, raw_line=raw_line)
					)
			continue

		if line.strip() and not line.startswith("-"):
			current.message = (current.message + "\n" + line.strip()).strip()

	return revisions


def _parse_xml_svn_log(log_text: str) -> List[SvnRevisionChange]:
	root = XmlET.fromstring(log_text)
	revisions: List[SvnRevisionChange] = []
	for logentry in root.findall(".//logentry"):
		revision_value = logentry.get("revision")
		if not revision_value:
			continue
		change = SvnRevisionChange(
			revision=int(revision_value),
			author=(logentry.findtext("author") or "").strip(),
			date=(logentry.findtext("date") or "").strip(),
			message=(logentry.findtext("msg") or "").strip(),
		)
		for path_node in logentry.findall("./paths/path"):
			path = (path_node.text or "").strip()
			fixed_path = normalize_fixed_path(path)
			if not fixed_path:
				continue
			action = (path_node.get("action") or "M").strip() or "M"
			change.paths.append(
				SvnChangedPath(action=action, path=path, fixed_path=fixed_path, raw_line=path)
			)
		revisions.append(change)
	return revisions


def parse_svn_log_text(log_text: str) -> List[SvnRevisionChange]:
	log_text = (log_text or "").strip()
	if not log_text:
		return []
	if log_text.startswith("<"):
		return _parse_xml_svn_log(log_text)
	return _parse_text_svn_log(log_text)


def build_file_list_from_svn_log(log_text: str, revision_spec: str) -> str:
	"""Build packer-compatible changed-path text from svn log -v output."""
	selected_revisions = set(parse_revision_spec(revision_spec))
	if not selected_revisions:
		raise RevisionSpecError("Current revision spec is empty.")

	lines: List[str] = []
	seen: Set[Tuple[str, str]] = set()
	for change in parse_svn_log_text(log_text):
		if change.revision not in selected_revisions:
			continue
		for changed_path in change.paths:
			key = (changed_path.action, changed_path.fixed_path)
			if key in seen:
				continue
			seen.add(key)
			lines.append(f"{changed_path.action} {changed_path.fixed_path}")

	if not lines:
		raise RevisionSpecError("No ServerBytes paths found for the selected revisions in svn log.")
	return "\n".join(lines)


def _normalize_scope_root(scope_root: str) -> Optional[str]:
	fixed = normalize_fixed_path(scope_root)
	if fixed:
		return fixed.rstrip("/")
	value = (scope_root or "").strip().replace("\\", "/")
	if not value:
		return None
	if not value.startswith("/"):
		value = "/" + value
	while "//" in value:
		value = value.replace("//", "/")
	return value.rstrip("/")


def _path_in_scope(fixed_path: str, scope_roots: Sequence[str]) -> bool:
	if not scope_roots:
		return True
	path = fixed_path.rstrip("/")
	for scope_root in scope_roots:
		root = scope_root.rstrip("/")
		if path == root or path.startswith(root + "/"):
			return True
	return False


def describe_fixed_path(fixed_path: str) -> Dict[str, str]:
	return describe_svn_path(fixed_path)


def _add_path_warning(
	groups: Dict[Tuple[str, str], Dict[str, object]],
	*,
	warning_type: str,
	message_prefix: str,
	revision: int,
	changed_path: SvnChangedPath,
	input_method: str,
	path_mappings: Sequence[Mapping[str, object]] = (),
) -> None:
	key = (warning_type, changed_path.fixed_path)
	description = describe_svn_path(changed_path.fixed_path, path_mappings)
	if key not in groups:
		groups[key] = {
			"type": warning_type,
			"level": "warning",
			"input_method": input_method,
			"module": description["module"],
			"table_name": description["table_name"],
			"readable_name": description["readable_name"],
			"mapping_source": description["mapping_source"],
			"directory": description["directory"],
			"file_name": description["file_name"],
			"fixed_path": changed_path.fixed_path,
			"revisions": [],
			"actions": [],
			"message": f"{message_prefix}: {description['readable_name']} ({changed_path.fixed_path})",
		}
	group = groups[key]
	revisions = group["revisions"]
	actions = group["actions"]
	if isinstance(revisions, list) and revision not in revisions:
		revisions.append(revision)
	if isinstance(actions, list) and changed_path.action not in actions:
		actions.append(changed_path.action)


def _get_commit_config(validation_config: Optional[Dict[str, object]]) -> Dict[str, object]:
	if not validation_config:
		return {}
	value = validation_config.get("commit_record")
	if isinstance(value, dict):
		return value
	value = validation_config.get("commit_record_check")
	if isinstance(value, dict):
		return value
	return {}


def run_commit_record_check(
	*,
	fixed_paths: List[str],
	validation_config: Optional[Dict[str, object]],
) -> Dict[str, object]:
	config = _get_commit_config(validation_config)
	if not config or config.get("enabled") is False:
		return {
			"status": "skipped",
			"reason": "commit_record_check_disabled",
			"warnings": [],
		}

	input_method = str(config.get("input_method") or "pasted_svn_file_list").strip()
	if input_method not in {"pasted_svn_file_list", "revision_spec"}:
		input_method = "pasted_svn_file_list"

	current_spec = str(config.get("current_revision_spec") or config.get("revision_spec") or "").strip()
	last_external_spec = str(
		config.get("last_external_revision_spec")
		or config.get("baseline_revision_spec")
		or config.get("last_revision_spec")
		or ""
	).strip()
	last_external_time = str(config.get("last_external_time") or "").strip()
	svn_log_text = str(config.get("svn_log_text") or "").strip()
	path_mapping_values = config.get("path_mappings") or []
	path_mappings = [
		value for value in path_mapping_values
		if isinstance(value, dict)
	] if isinstance(path_mapping_values, list) else []

	try:
		current_revisions = parse_revision_spec(current_spec)
		last_external_revisions = parse_revision_spec(last_external_spec)
	except RevisionSpecError as err:
		return {
			"status": "error",
			"reason": "invalid_revision_spec",
			"message": str(err),
			"warnings": [],
		}

	if input_method == "revision_spec" and not current_revisions:
		return {
			"status": "error",
			"reason": "missing_current_revision_spec",
			"message": "选择 revision 输入方式时必须填写本次打包 revision。",
			"warnings": [],
		}

	if input_method == "pasted_svn_file_list" and not current_revisions:
		return {
			"status": "skipped",
			"reason": "manual_file_list_without_revision_spec",
			"input_method": input_method,
			"input_method_label": "粘贴指定 SVN 文件列表",
			"message": "本次使用手动粘贴文件列表，未提供本次 revision，提交记录差异校验跳过；报告已标注输入方式。",
			"warnings": [],
		}

	scope_values = config.get("scope_roots") or config.get("pack_scope_roots") or []
	scope_roots: List[str] = []
	if isinstance(scope_values, str):
		scope_values = [scope_values]
	if isinstance(scope_values, list):
		for value in scope_values:
			if isinstance(value, str):
				normalized_scope = _normalize_scope_root(value)
				if normalized_scope:
					scope_roots.append(normalized_scope)

	package_path_set = {
		path for path in (normalize_fixed_path(path) for path in fixed_paths) if path and _path_in_scope(path, scope_roots)
	}

	revision_changes = parse_svn_log_text(svn_log_text) if svn_log_text else []
	change_by_revision = {change.revision: change for change in revision_changes}

	warning_groups: Dict[Tuple[str, str], Dict[str, object]] = {}
	unresolved_gap_revisions: List[int] = []
	unresolved_selected_revisions: List[int] = []

	baseline_max = max(last_external_revisions) if last_external_revisions else None
	current_max = max(current_revisions) if current_revisions else None
	expected_revisions: Set[int] = set()
	if baseline_max is not None and current_max is not None and current_max > baseline_max:
		expected_revisions = set(range(baseline_max + 1, current_max + 1))
	excluded_revisions = sorted(expected_revisions.difference(current_revisions))

	for revision in excluded_revisions:
		change = change_by_revision.get(revision)
		if change is None:
			unresolved_gap_revisions.append(revision)
			continue
		for changed_path in change.paths:
			if not _path_in_scope(changed_path.fixed_path, scope_roots):
				continue
			_add_path_warning(
				warning_groups,
				warning_type="unpackaged_change_between_releases",
				message_prefix="两次对外之间存在未纳入本次包的改动",
				revision=revision,
				changed_path=changed_path,
				input_method=input_method,
				path_mappings=path_mappings,
			)

	for revision in current_revisions:
		change = change_by_revision.get(revision)
		if change is None:
			if svn_log_text:
				unresolved_selected_revisions.append(revision)
			continue
		for changed_path in change.paths:
			if not _path_in_scope(changed_path.fixed_path, scope_roots):
				continue
			if changed_path.action == "D":
				continue
			if changed_path.fixed_path not in package_path_set:
				_add_path_warning(
					warning_groups,
					warning_type="selected_revision_path_not_packaged",
					message_prefix="本次选择的 revision 有改动未出现在打包列表",
					revision=revision,
					changed_path=changed_path,
					input_method=input_method,
					path_mappings=path_mappings,
				)

	warnings = list(warning_groups.values())
	for warning in warnings:
		if isinstance(warning.get("revisions"), list):
			warning["revisions"] = sorted(warning["revisions"])  # type: ignore[index]
		if isinstance(warning.get("actions"), list):
			warning["actions"] = sorted(warning["actions"])  # type: ignore[index]

	if unresolved_gap_revisions:
		warnings.append({
			"type": "unresolved_revision_gap",
			"level": "warning",
			"input_method": input_method,
			"message": "检测到上次对外与本次包之间存在未覆盖 revision，但未提供对应 SVN log，无法映射到目录或表。",
			"revisions": unresolved_gap_revisions,
		})

	if unresolved_selected_revisions:
		warnings.append({
			"type": "missing_selected_revision_log",
			"level": "warning",
			"input_method": input_method,
			"message": "SVN log 中缺少部分本次选择 revision，无法确认这些 revision 的文件列表是否完整。",
			"revisions": unresolved_selected_revisions,
		})

	status = "warning" if warnings else "passed"
	return {
		"status": status,
		"input_method": input_method,
		"input_method_label": "输入 SVN revision" if input_method == "revision_spec" else "粘贴指定 SVN 文件列表",
		"last_external": {
			"time": last_external_time,
			"revision_spec": last_external_spec,
			"revisions": last_external_revisions,
		},
		"current_package": {
			"revision_spec": current_spec,
			"revisions": current_revisions,
			"package_path_count": len(package_path_set),
			"package_paths_source": input_method,
		},
		"comparison": {
			"expected_revision_spec": summarize_revision_list(sorted(expected_revisions)),
			"included_revision_spec": summarize_revision_list(current_revisions),
			"excluded_revision_spec": summarize_revision_list(excluded_revisions),
			"scope_roots": scope_roots,
			"svn_log_provided": bool(svn_log_text),
		},
		"warning_count": len(warnings),
		"warnings": warnings,
	}
