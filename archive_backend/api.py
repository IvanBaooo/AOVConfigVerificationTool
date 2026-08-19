from __future__ import annotations

import hmac
import json
import re
from dataclasses import dataclass, field
from typing import Mapping
from urllib.parse import parse_qs, unquote, urlsplit

from backend_archive_contract_v1 import ARCHIVE_CONTRACT_VERSION
from validation_rule_sets import (
	IDENTIFIER_PATTERN,
	SUPPORTED_REGIONS,
	ValidationRuleSetError,
	effective_rule_set,
	validate_rule_set,
)

from .repository import ArchiveConflict, ArchiveRepository
from .schema_validation import ArchivePayloadError, ArchivePayloadValidator


PACKAGE_ID_PATTERN = re.compile(r"^(?!\.{1,2}$)[A-Za-z0-9._-]{1,128}$")
MAX_LIST_OFFSET = 1_000_000
DASHBOARD_REGIONS = ("TW", "TH", "VN", "ID")
ALLOWED_LIST_QUERY = frozenset(
	{
		"limit",
		"offset",
		"region_code",
		"package_version",
		"package_status",
		"validation_status",
		"record_state",
	}
)


@dataclass(frozen=True)
class ApiResponse:
	status: int
	body: dict[str, object]
	headers: dict[str, str] = field(default_factory=dict)


def _error(status: int, code: str, message: str, **extra: object) -> ApiResponse:
	error: dict[str, object] = {"code": code, "message": message}
	error.update(extra)
	return ApiResponse(status, {"error": error})


def _normalized_headers(headers: Mapping[str, str]) -> dict[str, str]:
	return {str(key).lower(): str(value).strip() for key, value in headers.items()}


class ArchiveApplication:
	def __init__(
		self,
		*,
		repository: ArchiveRepository,
		validator: ArchivePayloadValidator,
		access_token: str | None,
	) -> None:
		if access_token is not None and (not isinstance(access_token, str) or not access_token):
			raise ValueError("The backend access token must be non-empty when enabled.")
		self.repository = repository
		self.validator = validator
		self._authorization = None if access_token is None else f"Bearer {access_token}"

	def handle(
		self,
		method: str,
		target: str,
		headers: Mapping[str, str],
		body: bytes = b"",
	) -> ApiResponse:
		method = method.upper()
		try:
			parsed = urlsplit(target)
		except ValueError:
			return _error(400, "invalid_target", "The request target is invalid.")
		path = parsed.path
		normalized_headers = _normalized_headers(headers)

		if path == "/health":
			if method != "GET":
				return _error(405, "method_not_allowed", "Only GET is allowed.")
			healthy = self.repository.health_check()
			return ApiResponse(
				200 if healthy else 503,
				{
					"status": "ok" if healthy else "unavailable",
					"service": "aov-archive-backend",
					"contract_version": ARCHIVE_CONTRACT_VERSION,
					"auth_required": self._authorization is not None,
				},
			)

		if method == "GET" and path == "/api/v1/validation-rules/latest":
			return self._latest_validation_rules(parsed.query)
		if method == "GET" and path == "/api/v1/validation-rule-sets":
			return self._list_validation_rule_sets(parsed.query)
		rule_detail_prefix = "/api/v1/validation-rule-sets/"
		if method == "GET" and path.startswith(rule_detail_prefix):
			return self._get_validation_rule_set(path[len(rule_detail_prefix) :])
		if not self._authorized(normalized_headers.get("authorization", "")):
			return _error(401, "unauthorized", "A valid bearer token is required.")

		if path == "/api/v1/dashboard-summary":
			if method != "GET":
				return _error(405, "method_not_allowed", "Only GET is allowed.")
			if parsed.query:
				return _error(400, "invalid_query", "Dashboard summary does not accept query parameters.")
			return ApiResponse(200, self.repository.get_dashboard_summary(DASHBOARD_REGIONS))

		if path == "/api/v1/validation-rule-sets":
			if method != "POST":
				return _error(405, "method_not_allowed", "Only GET and POST are allowed.")
			return self._publish_rule_set(normalized_headers, body)

		if path == "/api/v1/release-baselines/latest":
			if method != "GET":
				return _error(405, "method_not_allowed", "Only GET is allowed.")
			return self._latest_release_baseline(parsed.query)
		if path == "/api/v1/validation-rules/latest" or path.startswith(rule_detail_prefix):
			return _error(405, "method_not_allowed", "Only GET is allowed.")
		if path == "/api/v1/package-archives":
			if method == "POST":
				return self._create_archive(normalized_headers, body)
			if method == "GET":
				return self._list_archives(parsed.query)
			return _error(405, "method_not_allowed", "Only GET and POST are allowed.")

		admin_prefix = "/api/v1/admin/package-archives/"
		if path.startswith(admin_prefix):
			return self._manage_archive(method, path[len(admin_prefix) :], normalized_headers, body)
		baseline_admin_prefix = "/api/v1/admin/release-baselines/"
		if path.startswith(baseline_admin_prefix):
			return self._set_release_baseline(
				method,
				path[len(baseline_admin_prefix) :],
				normalized_headers,
				body,
			)
		if path == "/api/v1/admin/archive-audit":
			if method != "GET":
				return _error(405, "method_not_allowed", "Only GET is allowed.")
			return self._list_archive_audit(parsed.query)

		prefix = "/api/v1/package-archives/"
		if path.startswith(prefix):
			if method != "GET":
				return _error(405, "method_not_allowed", "Only GET is allowed.")
			package_id = unquote(path[len(prefix) :])
			if not PACKAGE_ID_PATTERN.fullmatch(package_id):
				return _error(404, "archive_not_found", "The archive record was not found.")
			payload = self.repository.get_archive(package_id)
			if payload is None:
				return _error(404, "archive_not_found", "The archive record was not found.")
			management = self.repository.get_archive_management(package_id)
			return ApiResponse(200, {"archive": payload, "management": management or {}})

		return _error(404, "route_not_found", "The API route was not found.")

	def is_authorized(self, headers: Mapping[str, str]) -> bool:
		normalized_headers = _normalized_headers(headers)
		return self._authorized(normalized_headers.get("authorization", ""))

	def _authorized(self, authorization: str) -> bool:
		if self._authorization is None:
			return True
		return hmac.compare_digest(authorization.encode("utf-8"), self._authorization.encode("utf-8"))

	def _list_validation_rule_sets(self, query: str) -> ApiResponse:
		parameters = parse_qs(query, keep_blank_values=True)
		if set(parameters) - {"limit", "offset"} or any(len(values) != 1 for values in parameters.values()):
			return _error(400, "invalid_query", "The rule set query contains unsupported parameters.")
		try:
			limit = int(parameters.get("limit", ["50"])[0])
			offset = int(parameters.get("offset", ["0"])[0])
		except ValueError:
			return _error(400, "invalid_query", "limit and offset must be integers.")
		if not 1 <= limit <= 200 or not 0 <= offset <= MAX_LIST_OFFSET:
			return _error(400, "invalid_query", "The rule set pagination is out of range.")
		return ApiResponse(200, self.repository.list_rule_sets(limit=limit, offset=offset))

	def _get_validation_rule_set(self, suffix: str) -> ApiResponse:
		parts = suffix.split("/")
		if len(parts) != 2:
			return _error(404, "rule_set_not_found", "The validation rule set was not found.")
		rule_set_id, version = (unquote(part) for part in parts)
		if not IDENTIFIER_PATTERN.fullmatch(rule_set_id) or not IDENTIFIER_PATTERN.fullmatch(version):
			return _error(404, "rule_set_not_found", "The validation rule set was not found.")
		rule_set = self.repository.get_rule_set(rule_set_id, version)
		if rule_set is None:
			return _error(404, "rule_set_not_found", "The validation rule set was not found.")
		return ApiResponse(200, {"rule_set": rule_set})
	def _publish_rule_set(self, headers: Mapping[str, str], body: bytes) -> ApiResponse:
		content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
		if content_type != "application/json":
			return _error(415, "unsupported_media_type", "Content-Type must be application/json.")
		try:
			payload = json.loads(
				body.decode("utf-8"),
				parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
			)
		except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
			return _error(400, "invalid_json", "The request body is not valid UTF-8 JSON.")
		try:
			validated = validate_rule_set(payload)
		except ValidationRuleSetError as error:
			return _error(422, "invalid_rule_set", str(error))
		try:
			result = self.repository.publish_rule_set(validated)
		except ArchiveConflict as conflict:
			return _error(409, conflict.code, str(conflict))
		return ApiResponse(
			201 if result.result == "created" else 200,
			{
				"result": result.result,
				"rule_set": {
					"rule_set_id": result.rule_set_id,
					"version": result.version,
					"published_at": result.published_at,
					"payload_sha256": result.payload_sha256,
				},
			},
			{"Idempotency-Replayed": "true"} if result.result == "replayed" else {},
		)

	def _latest_validation_rules(self, query: str) -> ApiResponse:
		parameters = parse_qs(query, keep_blank_values=True)
		if set(parameters) != {"region_code"} or len(parameters["region_code"]) != 1:
			return _error(400, "invalid_query", "A single region_code query parameter is required.")
		region_code = parameters["region_code"][0].strip().upper()
		rule_set = self.repository.get_latest_rule_set()
		if rule_set is None:
			return _error(404, "rules_not_published", "No validation rule set has been published.")
		try:
			effective = effective_rule_set(rule_set, region_code)
		except ValidationRuleSetError as error:
			return _error(400, "invalid_query", str(error))
		return ApiResponse(200, {"rule_set": effective})

	def _latest_release_baseline(self, query: str) -> ApiResponse:
		parameters = parse_qs(query, keep_blank_values=True)
		if set(parameters) != {"region_code"} or len(parameters["region_code"]) != 1:
			return _error(400, "invalid_query", "A single region_code query parameter is required.")
		region_code = parameters["region_code"][0].strip().upper()
		if region_code not in SUPPORTED_REGIONS:
			return _error(400, "invalid_query", f"Unsupported region_code: {region_code}")
		baseline = self.repository.get_latest_release_baseline(region_code)
		if baseline is None:
			return _error(
				404,
				"release_baseline_not_found",
				"No archived release baseline exists for this region.",
			)
		return ApiResponse(200, {"baseline": baseline})

	def _create_archive(self, headers: Mapping[str, str], body: bytes) -> ApiResponse:
		content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
		if content_type != "application/json":
			return _error(415, "unsupported_media_type", "Content-Type must be application/json.")
		try:
			payload = json.loads(
				body.decode("utf-8"),
				parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
			)
		except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
			return _error(400, "invalid_json", "The request body is not valid UTF-8 JSON.")

		try:
			validated = self.validator.validate(payload)
		except ArchivePayloadError as error:
			return _error(
				422,
				"invalid_payload",
				str(error),
				details=error.details,
			)

		contract_version = headers.get("x-aov-contract-version", "")
		if contract_version != ARCHIVE_CONTRACT_VERSION:
			return _error(
				400,
				"contract_version_mismatch",
				f"X-AOV-Contract-Version must be {ARCHIVE_CONTRACT_VERSION}.",
			)
		request_key = headers.get("idempotency-key", "")
		payload_key = str(validated["idempotency_key"])
		if not hmac.compare_digest(request_key.encode("utf-8"), payload_key.encode("utf-8")):
			return _error(
				400,
				"idempotency_key_mismatch",
				"Idempotency-Key must match payload.idempotency_key.",
			)

		try:
			result = self.repository.create_archive(validated)
		except ArchiveConflict as conflict:
			return _error(409, conflict.code, str(conflict))
		response_headers = {"Idempotency-Replayed": "true"} if result.result == "replayed" else {}
		return ApiResponse(
			201 if result.result == "created" else 200,
			{"result": result.result, "archive": result.summary},
			response_headers,
		)

	def _list_archives(self, query: str) -> ApiResponse:
		parameters = parse_qs(query, keep_blank_values=True)
		if set(parameters) - ALLOWED_LIST_QUERY or any(len(values) != 1 for values in parameters.values()):
			return _error(400, "invalid_query", "The archive query contains unsupported parameters.")
		try:
			limit = int(parameters.get("limit", ["50"])[0])
			offset = int(parameters.get("offset", ["0"])[0])
		except ValueError:
			return _error(400, "invalid_query", "limit and offset must be integers.")
		if not 1 <= limit <= 200 or not 0 <= offset <= MAX_LIST_OFFSET:
			return _error(
				400,
				"invalid_query",
				f"limit must be 1-200 and offset must be 0-{MAX_LIST_OFFSET}.",
			)

		filters: dict[str, str | None] = {}
		for key in ("region_code", "package_version", "package_status", "validation_status"):
			value = parameters.get(key, [None])[0]
			if value is not None and (not value or len(value) > 128):
				return _error(400, "invalid_query", f"Invalid {key} filter.")
			filters[key] = value
		record_state = parameters.get("record_state", ["active"])[0]
		if record_state not in {"active", "deleted", "all"}:
			return _error(400, "invalid_query", "Invalid record_state filter.")
		result = self.repository.list_archives(
			limit=limit,
			offset=offset,
			record_state=record_state,
			**filters,
		)
		return ApiResponse(200, result)

	def _manage_archive(
		self,
		method: str,
		suffix: str,
		headers: Mapping[str, str],
		body: bytes,
	) -> ApiResponse:
		parts = suffix.split("/")
		if len(parts) != 2 or parts[1] not in {"soft-delete", "restore"}:
			return _error(404, "route_not_found", "The API route was not found.")
		if method != "POST":
			return _error(405, "method_not_allowed", "Only POST is allowed.")
		package_id = unquote(parts[0])
		if not PACKAGE_ID_PATTERN.fullmatch(package_id):
			return _error(404, "archive_not_found", "The archive record was not found.")
		content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
		if content_type != "application/json":
			return _error(415, "unsupported_media_type", "Content-Type must be application/json.")
		try:
			payload = json.loads(body.decode("utf-8"))
		except (UnicodeDecodeError, json.JSONDecodeError):
			return _error(400, "invalid_json", "The request body is not valid UTF-8 JSON.")
		if not isinstance(payload, dict):
			return _error(422, "invalid_management_request", "The request body must be an object.")
		reason = payload.get("reason")
		if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
			return _error(
				422,
				"invalid_management_request",
				"A management reason of 1-500 characters is required.",
			)
		replacement_package_id = payload.get("replacement_package_id")
		if replacement_package_id is not None and (
			not isinstance(replacement_package_id, str)
			or not PACKAGE_ID_PATTERN.fullmatch(replacement_package_id)
		):
			return _error(
				422,
				"invalid_management_request",
				"replacement_package_id must be a valid package ID.",
			)
		try:
			if parts[1] == "soft-delete":
				event = self.repository.soft_delete_archive(
					package_id,
					actor="admin",
					reason=reason.strip(),
					replacement_package_id=replacement_package_id,
				)
				result = "deleted"
			else:
				event = self.repository.restore_archive(
					package_id,
					actor="admin",
					reason=reason.strip(),
				)
				result = "restored"
		except ArchiveConflict as conflict:
			status = 404 if conflict.code == "archive_not_found" else 409
			return _error(status, conflict.code, str(conflict))
		return ApiResponse(200, {"result": result, "event": event})

	def _set_release_baseline(
		self,
		method: str,
		region_suffix: str,
		headers: Mapping[str, str],
		body: bytes,
	) -> ApiResponse:
		if method != "POST":
			return _error(405, "method_not_allowed", "Only POST is allowed.")
		region_code = unquote(region_suffix).strip().upper()
		if region_code not in SUPPORTED_REGIONS:
			return _error(404, "region_not_found", "The release region was not found.")
		content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
		if content_type != "application/json":
			return _error(415, "unsupported_media_type", "Content-Type must be application/json.")
		try:
			payload = json.loads(body.decode("utf-8"))
		except (UnicodeDecodeError, json.JSONDecodeError):
			return _error(400, "invalid_json", "The request body is not valid UTF-8 JSON.")
		if not isinstance(payload, dict):
			return _error(422, "invalid_management_request", "The request body must be an object.")
		package_id = payload.get("package_id")
		reason = payload.get("reason")
		if not isinstance(package_id, str) or not PACKAGE_ID_PATTERN.fullmatch(package_id):
			return _error(422, "invalid_management_request", "A valid package_id is required.")
		if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
			return _error(
				422,
				"invalid_management_request",
				"A management reason of 1-500 characters is required.",
			)
		management = self.repository.get_archive_management(package_id)
		if management is None or management.get("region_code") != region_code:
			return _error(404, "archive_not_found", "The archive record was not found in this region.")
		try:
			baseline = self.repository.set_release_baseline(
				package_id,
				actor="admin",
				reason=reason.strip(),
			)
		except ArchiveConflict as conflict:
			status = 404 if conflict.code == "archive_not_found" else 409
			return _error(status, conflict.code, str(conflict))
		return ApiResponse(200, {"result": "baseline_updated", "baseline": baseline})
	def _list_archive_audit(self, query: str) -> ApiResponse:
		parameters = parse_qs(query, keep_blank_values=True)
		allowed = {"limit", "offset", "action", "region_code"}
		if set(parameters) - allowed or any(len(values) != 1 for values in parameters.values()):
			return _error(400, "invalid_query", "The audit query contains unsupported parameters.")
		try:
			limit = int(parameters.get("limit", ["100"])[0])
			offset = int(parameters.get("offset", ["0"])[0])
		except ValueError:
			return _error(400, "invalid_query", "limit and offset must be integers.")
		if not 1 <= limit <= 200 or not 0 <= offset <= MAX_LIST_OFFSET:
			return _error(400, "invalid_query", "The audit pagination is out of range.")
		action = parameters.get("action", [None])[0]
		if action is not None and action not in {"delete", "restore", "baseline_set"}:
			return _error(400, "invalid_query", "Invalid audit action filter.")
		region_code = parameters.get("region_code", [None])[0]
		if region_code is not None:
			region_code = region_code.strip().upper()
			if region_code not in SUPPORTED_REGIONS:
				return _error(400, "invalid_query", "Invalid audit region filter.")
		return ApiResponse(
			200,
			self.repository.list_archive_audit(
				limit=limit,
				offset=offset,
				action=action,
				region_code=region_code,
			),
		)

__all__ = ["ApiResponse", "ArchiveApplication"]

