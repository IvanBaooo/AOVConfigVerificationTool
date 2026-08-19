from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


SUPPORTED_REGIONS = frozenset({"TW", "TH", "VN", "ID"})


class ReleaseBaselineClientError(RuntimeError):
	pass


@dataclass(frozen=True)
class BackendHealth:
	status: str
	service: str
	auth_required: bool


@dataclass(frozen=True)
class ReleaseBaseline:
	region_code: str
	package_id: str
	release_time: str
	package_created_at: str
	released_revision_spec: str
	released_revisions: tuple[int, ...]
	last_checked_revision: int
	package_version: str


def _required_text(value: object, field: str) -> str:
	if not isinstance(value, str) or not value.strip():
		raise ReleaseBaselineClientError(f"Baseline response has invalid {field}.")
	return value.strip()


def _parse_baseline(value: object, expected_region: str) -> ReleaseBaseline:
	if not isinstance(value, dict):
		raise ReleaseBaselineClientError("Baseline response is missing baseline.")
	region_code = _required_text(value.get("region_code"), "region_code").upper()
	if region_code != expected_region:
		raise ReleaseBaselineClientError("Baseline response region does not match the request.")
	revisions_value = value.get("released_revisions")
	if not isinstance(revisions_value, list) or not revisions_value:
		raise ReleaseBaselineClientError("Baseline has no released revisions.")
	revisions: list[int] = []
	for revision in revisions_value:
		if not isinstance(revision, int) or isinstance(revision, bool) or revision <= 0:
			raise ReleaseBaselineClientError("Baseline contains an invalid revision.")
		if revision in revisions:
			raise ReleaseBaselineClientError("Baseline contains duplicate revisions.")
		revisions.append(revision)
	last_checked = value.get("last_checked_revision")
	if last_checked != max(revisions):
		raise ReleaseBaselineClientError("Baseline last_checked_revision is inconsistent.")
	return ReleaseBaseline(
		region_code=region_code,
		package_id=_required_text(value.get("package_id"), "package_id"),
		release_time=_required_text(value.get("release_time"), "release_time"),
		package_created_at=_required_text(value.get("package_created_at"), "package_created_at"),
		released_revision_spec=_required_text(
			value.get("released_revision_spec"), "released_revision_spec"
		),
		released_revisions=tuple(revisions),
		last_checked_revision=last_checked,
		package_version=str(value.get("package_version") or "").strip(),
	)


class ReleaseBaselineClient:
	def __init__(
		self,
		*,
		timeout_seconds: float = 5.0,
		opener: Callable[..., object] = urlopen,
	) -> None:
		if timeout_seconds <= 0:
			raise ValueError("Baseline request timeout must be positive.")
		self.timeout_seconds = timeout_seconds
		self._opener = opener

	def _base_url(self, base_url: str) -> str:
		value = base_url.strip().rstrip("/")
		parsed = urlsplit(value)
		if parsed.scheme not in {"http", "https"} or not parsed.netloc:
			raise ReleaseBaselineClientError("Backend URL must be an absolute HTTP(S) URL.")
		return value

	def check_health(self, *, base_url: str) -> BackendHealth:
		request = Request(
			f"{self._base_url(base_url)}/health",
			headers={"Accept": "application/json"},
			method="GET",
		)
		try:
			with self._opener(request, timeout=self.timeout_seconds) as response:
				payload = json.loads(response.read().decode("utf-8"))
		except HTTPError as error:
			raise ReleaseBaselineClientError(
				f"Backend health check returned HTTP {error.code}."
			) from error
		except URLError as error:
			raise ReleaseBaselineClientError(f"Cannot connect to backend: {error.reason}") from error
		except (UnicodeDecodeError, json.JSONDecodeError) as error:
			raise ReleaseBaselineClientError("Backend health check returned invalid JSON.") from error
		if not isinstance(payload, dict) or payload.get("status") != "ok":
			raise ReleaseBaselineClientError("Backend health check is unavailable.")
		auth_required = payload.get("auth_required")
		if not isinstance(auth_required, bool):
			raise ReleaseBaselineClientError("Backend health response has invalid auth_required.")
		return BackendHealth(
			status="ok",
			service=str(payload.get("service") or "aov-archive-backend"),
			auth_required=auth_required,
		)

	def fetch(
		self,
		*,
		base_url: str,
		region_code: str,
		access_token: str = "",
	) -> ReleaseBaseline:
		base_url = self._base_url(base_url)
		region = region_code.strip().upper()
		if region not in SUPPORTED_REGIONS:
			raise ReleaseBaselineClientError(f"Unsupported region_code: {region_code}")
		query = urlencode({"region_code": region})
		url = f"{base_url}/api/v1/release-baselines/latest?{query}"
		headers = {"Accept": "application/json"}
		if access_token:
			headers["Authorization"] = f"Bearer {access_token}"
		request = Request(url, headers=headers, method="GET")
		try:
			with self._opener(request, timeout=self.timeout_seconds) as response:
				payload = json.loads(response.read().decode("utf-8"))
		except HTTPError as error:
			try:
				payload = json.loads(error.read().decode("utf-8"))
				message = payload.get("error", {}).get("message", "")
			except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
				message = ""
			raise ReleaseBaselineClientError(
				message or f"Baseline backend returned HTTP {error.code}."
			) from error
		except URLError as error:
			raise ReleaseBaselineClientError(f"Cannot connect to baseline backend: {error.reason}") from error
		except (UnicodeDecodeError, json.JSONDecodeError) as error:
			raise ReleaseBaselineClientError("Baseline backend returned invalid JSON.") from error
		if not isinstance(payload, dict):
			raise ReleaseBaselineClientError("Baseline backend response must be a JSON object.")
		return _parse_baseline(payload.get("baseline"), region)


__all__ = [
	"BackendHealth",
	"ReleaseBaseline",
	"ReleaseBaselineClient",
	"ReleaseBaselineClientError",
]