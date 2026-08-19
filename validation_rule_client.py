from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from local_settings import default_settings_path
from validation_rule_sets import (
	RULE_SCHEMA_VERSION,
	SUPPORTED_REGIONS,
	ValidationRuleSetError,
	rule_sha256,
	validate_effective_rule_set,
)


RULE_CACHE_SCHEMA_VERSION = 1
RULE_CACHE_ENV = "AOV_VALIDATION_RULE_CACHE"


class ValidationRuleClientError(RuntimeError):
	pass


@dataclass(frozen=True)
class RuleLoadResult:
	rule_set: dict[str, object]
	source: str
	message: str = ""


def default_rule_cache_path() -> Path:
	override = os.environ.get(RULE_CACHE_ENV, "").strip()
	if override:
		return Path(override).expanduser()
	return default_settings_path().parent / "validation_rules.json"


def built_in_rule_set(region_code: str) -> dict[str, object]:
	region = region_code.strip().upper()
	if region not in SUPPORTED_REGIONS:
		raise ValidationRuleClientError(f"Unsupported region_code: {region_code}")
	effective: dict[str, object] = {
		"schema_version": RULE_SCHEMA_VERSION,
		"rule_set_id": "built-in",
		"version": "1",
		"published_at": "1970-01-01T00:00:00Z",
		"notes": "Program built-in fallback rules",
		"region_code": region,
		"rules": {
			"path_mappings": [],
			"whitelist_paths": [],
		},
	}
	effective["rule_hash"] = rule_sha256(effective)
	return effective


class ValidationRuleCache:
	def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
		self.path = Path(path) if path is not None else default_rule_cache_path()

	def load(self, region_code: str) -> dict[str, object] | None:
		region = region_code.strip().upper()
		try:
			document = json.loads(self.path.read_text(encoding="utf-8"))
		except FileNotFoundError:
			return None
		except (OSError, UnicodeError, json.JSONDecodeError) as error:
			raise ValidationRuleClientError(f"Cannot read validation rule cache: {error}") from error
		if not isinstance(document, dict) or document.get("schema_version") != RULE_CACHE_SCHEMA_VERSION:
			raise ValidationRuleClientError("Validation rule cache schema is unsupported.")
		regions = document.get("regions")
		if not isinstance(regions, dict):
			raise ValidationRuleClientError("Validation rule cache regions are invalid.")
		value = regions.get(region)
		if value is None:
			return None
		try:
			return validate_effective_rule_set(value)
		except ValidationRuleSetError as error:
			raise ValidationRuleClientError(f"Cached validation rules are invalid: {error}") from error

	def save(self, rule_set: dict[str, object]) -> Path:
		try:
			validated = validate_effective_rule_set(rule_set)
		except ValidationRuleSetError as error:
			raise ValidationRuleClientError(f"Cannot cache invalid validation rules: {error}") from error
		region = str(validated["region_code"])
		regions: dict[str, object] = {}
		try:
			existing = json.loads(self.path.read_text(encoding="utf-8"))
			if (
				isinstance(existing, dict)
				and existing.get("schema_version") == RULE_CACHE_SCHEMA_VERSION
				and isinstance(existing.get("regions"), dict)
			):
				regions.update(existing["regions"])
		except FileNotFoundError:
			pass
		except (OSError, UnicodeError, json.JSONDecodeError):
			pass
		regions[region] = validated
		document = {
			"schema_version": RULE_CACHE_SCHEMA_VERSION,
			"regions": regions,
		}
		serialized = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
		try:
			self.path.parent.mkdir(parents=True, exist_ok=True)
			temp_path = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
			temp_path.write_text(serialized, encoding="utf-8")
			os.replace(temp_path, self.path)
		except OSError as error:
			raise ValidationRuleClientError(f"Cannot save validation rule cache: {error}") from error
		finally:
			temp_path = locals().get("temp_path")
			if isinstance(temp_path, Path) and temp_path.exists():
				try:
					temp_path.unlink()
				except OSError:
					pass
		return self.path


class ValidationRuleClient:
	def __init__(
		self,
		*,
		cache: ValidationRuleCache | None = None,
		opener: Callable[..., object] = urlopen,
	) -> None:
		self.cache = cache or ValidationRuleCache()
		self._opener = opener

	def fetch_latest(
		self,
		*,
		base_url: str,
		region_code: str,
		access_token: str = "",
		timeout_seconds: float = 10.0,
	) -> dict[str, object]:
		parsed = urlsplit(base_url.strip())
		if parsed.scheme not in {"http", "https"} or not parsed.netloc:
			raise ValidationRuleClientError("Backend URL must be an absolute HTTP(S) URL.")
		if timeout_seconds <= 0:
			raise ValidationRuleClientError("Rule request timeout must be positive.")
		region = region_code.strip().upper()
		if region not in SUPPORTED_REGIONS:
			raise ValidationRuleClientError(f"Unsupported region_code: {region_code}")
		url = (
			base_url.rstrip("/")
			+ "/api/v1/validation-rules/latest?"
			+ urlencode({"region_code": region})
		)
		headers = {"Accept": "application/json"}
		if access_token:
			headers["Authorization"] = f"Bearer {access_token}"
		request = Request(url, method="GET", headers=headers)
		try:
			with self._opener(request, timeout=timeout_seconds) as response:
				document = json.loads(response.read().decode("utf-8"))
		except HTTPError as error:
			try:
				detail = json.loads(error.read().decode("utf-8")).get("error", {}).get("message", "")
			except Exception:
				detail = ""
			raise ValidationRuleClientError(
				f"Rule backend returned HTTP {error.code}" + (f": {detail}" if detail else "")
			) from error
		except (URLError, TimeoutError, OSError) as error:
			raise ValidationRuleClientError(f"Cannot connect to rule backend: {error}") from error
		except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError) as error:
			raise ValidationRuleClientError(f"Rule backend returned invalid JSON: {error}") from error
		if not isinstance(document, dict) or "rule_set" not in document:
			raise ValidationRuleClientError("Rule backend response is missing rule_set.")
		try:
			return validate_effective_rule_set(document["rule_set"])
		except ValidationRuleSetError as error:
			raise ValidationRuleClientError(f"Rule backend response failed validation: {error}") from error

	def resolve(
		self,
		*,
		base_url: str,
		region_code: str,
		access_token: str = "",
		timeout_seconds: float = 10.0,
	) -> RuleLoadResult:
		try:
			remote = self.fetch_latest(
				base_url=base_url,
				region_code=region_code,
				access_token=access_token,
				timeout_seconds=timeout_seconds,
			)
			try:
				self.cache.save(remote)
				return RuleLoadResult(remote, "remote")
			except ValidationRuleClientError as cache_error:
				return RuleLoadResult(remote, "remote", str(cache_error))
		except ValidationRuleClientError as remote_error:
			try:
				cached = self.cache.load(region_code)
			except ValidationRuleClientError as cache_error:
				fallback = built_in_rule_set(region_code)
				return RuleLoadResult(
					fallback,
					"built_in",
					f"{remote_error}; {cache_error}",
				)
			if cached is not None:
				return RuleLoadResult(cached, "local_cache", str(remote_error))
			return RuleLoadResult(built_in_rule_set(region_code), "built_in", str(remote_error))
