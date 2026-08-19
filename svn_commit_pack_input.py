from __future__ import annotations

from typing import List, Set, Tuple

from svn_commit_validation import RevisionSpecError, parse_revision_spec, parse_svn_log_text


def build_packer_file_list_from_svn_log(log_text: str, revision_spec: str) -> str:
	"""Build AOVAutoPacker-compatible changed-path text from svn log -v output.

	The existing packer parser expects each line to contain the ServerBytes anchor,
	so this returns lines such as:
	M ServerBytes/Taiwan/Databin/Server/Shop/SvrHeroSkinShop.xml
	"""
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
			lines.append(f"{changed_path.action} ServerBytes{changed_path.fixed_path}")

	if not lines:
		raise RevisionSpecError("No ServerBytes paths found for the selected revisions in svn log.")
	return "\n".join(lines)
