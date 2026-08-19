from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import List, Optional

from svn_cli_log import build_revision_span
from svn_commit_validation import RevisionSpecError


@dataclass
class SvnAuthLogFetchResult:
	command: List[str]
	safe_command: List[str]
	stdout: str
	stderr: str
	returncode: int


def decode_svn_console_output(value: bytes | str) -> str:
	if isinstance(value, str):
		return value
	for encoding in ("utf-8", "mbcs", "gb18030"):
		try:
			return value.decode(encoding)
		except (LookupError, UnicodeDecodeError):
			continue
	return value.decode("utf-8", errors="replace")


def fetch_svn_log_with_auth(
	*,
	svn_target: str,
	current_revision_spec: str,
	last_external_revision_spec: str = "",
	svn_exe: Optional[str] = None,
	username: str = "",
	password: str = "",
	use_auth_cache: bool = True,
) -> SvnAuthLogFetchResult:
	target = (svn_target or "").strip()
	if not target:
		raise RevisionSpecError("SVN target is empty.")

	exe = (svn_exe or "svn").strip() or "svn"
	revision_span = build_revision_span(current_revision_spec, last_external_revision_spec)
	command = [
		exe,
		"log",
		"-v",
		"--xml",
		"-r",
		revision_span,
		"--non-interactive",
	]
	safe_command = list(command)

	if not use_auth_cache:
		command.append("--no-auth-cache")
		safe_command.append("--no-auth-cache")

	if username.strip():
		command.extend(["--username", username.strip()])
		safe_command.extend(["--username", username.strip()])
	if password:
		command.extend(["--password", password])
		safe_command.extend(["--password", "***"])

	command.append(target)
	safe_command.append(target)

	completed = subprocess.run(
		command,
		capture_output=True,
		check=False,
	)
	return SvnAuthLogFetchResult(
		command=command,
		safe_command=safe_command,
		stdout=decode_svn_console_output(completed.stdout),
		stderr=decode_svn_console_output(completed.stderr),
		returncode=completed.returncode,
	)
