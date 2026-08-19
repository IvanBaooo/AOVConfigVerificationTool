from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import List, Optional

from svn_commit_validation import RevisionSpecError, parse_revision_spec


@dataclass
class SvnLogFetchResult:
	command: List[str]
	stdout: str
	stderr: str
	returncode: int


def build_revision_span(current_revision_spec: str, last_external_revision_spec: str = "") -> str:
	current_revisions = parse_revision_spec(current_revision_spec)
	last_external_revisions = parse_revision_spec(last_external_revision_spec)
	if not current_revisions:
		raise RevisionSpecError("Current revision spec is empty.")

	current_max = max(current_revisions)
	if last_external_revisions:
		start = max(last_external_revisions) + 1
	else:
		start = min(current_revisions)
	if start > current_max:
		start = min(current_revisions)
	return f"{start}:{current_max}"


def fetch_svn_log(
	*,
	svn_target: str,
	current_revision_spec: str,
	last_external_revision_spec: str = "",
	svn_exe: Optional[str] = None,
) -> SvnLogFetchResult:
	target = (svn_target or "").strip()
	if not target:
		raise RevisionSpecError("SVN target is empty.")

	exe = (svn_exe or "svn").strip() or "svn"
	revision_span = build_revision_span(current_revision_spec, last_external_revision_spec)
	command = [
		exe,
		"log",
		"-v",
		"-r",
		revision_span,
		"--non-interactive",
		target,
	]
	completed = subprocess.run(
		command,
		capture_output=True,
		text=True,
		encoding="utf-8",
		errors="replace",
		check=False,
	)
	return SvnLogFetchResult(
		command=command,
		stdout=completed.stdout,
		stderr=completed.stderr,
		returncode=completed.returncode,
	)
