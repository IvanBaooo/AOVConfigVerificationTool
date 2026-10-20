from __future__ import annotations

import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Mapping
from urllib.parse import parse_qs, unquote, urlsplit

from backend_archive_contract_v1 import ARCHIVE_CONTRACT_VERSION
from rules.registry import all_rule_specs
from rules.sets import (
	IDENTIFIER_PATTERN,
	SUPPORTED_REGIONS,
	ValidationRuleSetError,
	effective_rule_set,
	validate_rule_set,
)

from .auth import (
	AUTH_MODE_GOOGLE,
	AUTH_MODE_IAM,
	AUTH_MODE_LEGACY_TOKEN,
	AUTH_MODE_NONE,
	IAM_STATE_COOKIE_NAME,
	SESSION_COOKIE_NAME,
	SESSION_TTL,
	Identity,
	build_iam_authorize_url,
	build_iam_signout_url,
	hash_secret,
	new_api_token,
	new_iam_state,
	new_session_id,
	parse_cookies,
	resolve_identity,
	session_expiry,
	verify_iam_state,
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
		"received_from",
		"received_to",
	}
)
DATE_FILTER_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]{1,128}@[^@\s]{1,190}\.[^@\s]+$")


def _parse_date_filter(value: str) -> str | None:
	if not DATE_FILTER_PATTERN.fullmatch(value):
		return None
	try:
		return date.fromisoformat(value).isoformat()
	except ValueError:
		return None


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
		auth_mode: str | None = None,
		google_verifier: object | None = None,
		iam_config: object | None = None,
		iam_client: object | None = None,
		secure_cookies: bool = False,
	) -> None:
		if access_token is not None and (not isinstance(access_token, str) or not access_token):
			raise ValueError("The backend access token must be non-empty when enabled.")
		if auth_mode is None:
			auth_mode = AUTH_MODE_NONE if access_token is None else AUTH_MODE_LEGACY_TOKEN
		if auth_mode not in {AUTH_MODE_NONE, AUTH_MODE_LEGACY_TOKEN, AUTH_MODE_GOOGLE, AUTH_MODE_IAM}:
			raise ValueError(f"Unsupported auth mode: {auth_mode}")
		if auth_mode == AUTH_MODE_GOOGLE and google_verifier is None:
			raise ValueError("Google auth mode requires a Google ID token verifier.")
		if auth_mode == AUTH_MODE_IAM and (iam_config is None or iam_client is None):
			raise ValueError("IAM auth mode requires an IAM config and client.")
		self.repository = repository
		self.validator = validator
		self.auth_mode = auth_mode
		self.google_verifier = google_verifier
		self.iam_config = iam_config
		self.iam_client = iam_client
		self.secure_cookies = secure_cookies
		self._legacy_token = access_token if auth_mode == AUTH_MODE_LEGACY_TOKEN else None
		self._auth_required = auth_mode != AUTH_MODE_NONE

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
					"auth_required": self._auth_required,
					"auth_mode": self.auth_mode,
					"google_client_id": (
						getattr(self.google_verifier, "client_id", "")
						if self.auth_mode == AUTH_MODE_GOOGLE
						else ""
					),
					"iam_signout_url": (
						build_iam_signout_url(self.iam_config)
						if self.auth_mode == AUTH_MODE_IAM
						else ""
					),
				},
			)

		if path == "/api/v1/auth/google" and method == "POST":
			return self._google_login(body)
		if path == "/auth/iam/login" and method == "GET":
			return self._iam_login_redirect()
		if path == "/auth/callback" and method == "GET":
			return self._iam_callback(parsed.query, normalized_headers)

		identity = resolve_identity(
			self.repository,
			self.auth_mode,
			self._legacy_token,
			normalized_headers,
		)
		if identity is None:
			return _error(401, "unauthorized", "Authentication is required.")

		if path == "/api/v1/auth/me":
			if method != "GET":
				return _error(405, "method_not_allowed", "Only GET is allowed.")
			return ApiResponse(200, {
				"user": {
					"email": identity.email,
					"display_name": identity.display_name,
					"role": identity.role,
				},
				"auth_mode": self.auth_mode,
			})
		if path == "/api/v1/auth/logout":
			if method != "POST":
				return _error(405, "method_not_allowed", "Only POST is allowed.")
			session_id = parse_cookies(normalized_headers.get("cookie")).get(SESSION_COOKIE_NAME)
			if session_id:
				self.repository.delete_session(hash_secret(session_id))
			return ApiResponse(
				200,
				{"result": "logged_out"},
				{"Set-Cookie": self._session_cookie("", max_age=0)},
			)
		if path == "/api/v1/tokens" or path.startswith("/api/v1/tokens/"):
			return self._manage_tokens(method, path, identity, body)
		if path == "/api/v1/admin/users" or path.startswith("/api/v1/admin/users/"):
			return self._manage_users(method, path, identity, body)

		if path.startswith("/api/v1/admin/") or (method == "POST" and path == "/api/v1/validation-rule-sets"):
			denied = self._require_admin(identity)
			if denied is not None:
				return denied

		if method == "GET" and path == "/api/v1/validation-rules/latest":
			return self._latest_validation_rules(parsed.query)
		if method == "GET" and path == "/api/v1/validation-rule-catalog":
			return ApiResponse(200, {
				"checks": [
					{"type": str(spec["type"]), "name": str(spec.get("name") or "")}
					for spec in all_rule_specs()
				],
			})
		if method == "GET" and path == "/api/v1/validation-rule-sets":
			return self._list_validation_rule_sets(parsed.query)
		rule_detail_prefix = "/api/v1/validation-rule-sets/"
		if method == "GET" and path.startswith(rule_detail_prefix):
			return self._get_validation_rule_set(path[len(rule_detail_prefix) :])

		if path == "/api/v1/dashboard-summary":
			if method != "GET":
				return _error(405, "method_not_allowed", "Only GET is allowed.")
			if parsed.query:
				return _error(400, "invalid_query", "Dashboard summary does not accept query parameters.")
			return ApiResponse(200, self.repository.get_dashboard_summary(DASHBOARD_REGIONS))

		if path == "/api/v1/dashboard-activity":
			if method != "GET":
				return _error(405, "method_not_allowed", "Only GET is allowed.")
			return self._dashboard_activity(parsed.query)

		if path == "/api/v1/dashboard-rule-stats":
			if method != "GET":
				return _error(405, "method_not_allowed", "Only GET is allowed.")
			return self._dashboard_rule_stats(parsed.query)

		if path == "/api/v1/validation-rule-sets":
			if method != "POST":
				return _error(405, "method_not_allowed", "Only GET and POST are allowed.")
			return self._publish_rule_set(normalized_headers, body)

		if path == "/api/v1/release-baselines/latest":
			if method != "GET":
				return _error(405, "method_not_allowed", "Only GET is allowed.")
			return self._latest_release_baseline(parsed.query)
		if path == "/api/v1/validation-rules/latest" or path == "/api/v1/validation-rule-catalog" or path.startswith(rule_detail_prefix):
			return _error(405, "method_not_allowed", "Only GET is allowed.")
		if path == "/api/v1/package-archives":
			if method == "POST":
				return self._create_archive(normalized_headers, body)
			if method == "GET":
				return self._list_archives(parsed.query)
			return _error(405, "method_not_allowed", "Only GET and POST are allowed.")

		admin_prefix = "/api/v1/admin/package-archives/"
		if path.startswith(admin_prefix):
			return self._manage_archive(method, path[len(admin_prefix) :], normalized_headers, body, actor=identity.email)
		baseline_admin_prefix = "/api/v1/admin/release-baselines/"
		if path.startswith(baseline_admin_prefix):
			return self._set_release_baseline(
				method,
				path[len(baseline_admin_prefix) :],
				normalized_headers,
				body,
				actor=identity.email,
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
		return resolve_identity(
			self.repository,
			self.auth_mode,
			self._legacy_token,
			normalized_headers,
		) is not None

	@staticmethod
	def _require_admin(identity: Identity) -> ApiResponse | None:
		if not identity.is_admin:
			return _error(403, "forbidden", "Administrator role is required.")
		return None

	def _session_cookie(self, session_id: str, *, max_age: int | None = None) -> str:
		if max_age is None:
			max_age = int(SESSION_TTL.total_seconds())
		parts = [
			f"{SESSION_COOKIE_NAME}={session_id}",
			"Path=/",
			"HttpOnly",
			"SameSite=Lax",
			f"Max-Age={max_age}",
		]
		if self.secure_cookies:
			parts.append("Secure")
		return "; ".join(parts)

	@staticmethod
	def _public_user(user: Mapping[str, object]) -> dict[str, object]:
		return {
			"id": user["id"],
			"email": user["email"],
			"display_name": user.get("display_name", ""),
			"role": user["role"],
		}

	def _complete_login(self, email: str, display_name: str) -> tuple[Mapping[str, object] | None, ApiResponse | None]:
		user = self.repository.get_user_by_email(email)
		if user is None:
			if self.repository.count_users() == 0:
				user = self.repository.create_user(email, display_name, role="admin")
			else:
				return None, _error(
					403,
					"not_in_whitelist",
					"This account is not authorized. Ask an administrator to add your email.",
				)
		if user["status"] != "active":
			return None, _error(403, "account_disabled", "This account has been disabled.")
		return user, None

	def _google_login(self, body: bytes) -> ApiResponse:
		if self.auth_mode != AUTH_MODE_GOOGLE or self.google_verifier is None:
			return _error(404, "route_not_found", "The API route was not found.")
		try:
			payload = json.loads(body.decode("utf-8"))
		except (UnicodeDecodeError, json.JSONDecodeError):
			return _error(400, "invalid_json", "The request body is not valid UTF-8 JSON.")
		credential = payload.get("credential") if isinstance(payload, dict) else None
		if not isinstance(credential, str) or not credential:
			return _error(422, "invalid_login_request", "A Google credential is required.")
		try:
			profile = self.google_verifier.verify(credential)
		except Exception:
			return _error(401, "invalid_google_token", "The Google credential could not be verified.")
		email = profile["email"].strip().lower()
		user, denied = self._complete_login(email, profile.get("display_name", ""))
		if denied is not None:
			return denied
		session_id = new_session_id()
		self.repository.create_session(hash_secret(session_id), int(user["id"]), session_expiry())
		self.repository.touch_user_login(int(user["id"]))
		return ApiResponse(
			200,
			{"user": self._public_user(user)},
			{"Set-Cookie": self._session_cookie(session_id)},
		)

	def _iam_state_cookie(self, state: str, *, max_age: int | None = None) -> str:
		if max_age is None:
			max_age = 600
		parts = [
			f"{IAM_STATE_COOKIE_NAME}={state}",
			"Path=/",
			"HttpOnly",
			"SameSite=Lax",
			f"Max-Age={max_age}",
		]
		if self.secure_cookies:
			parts.append("Secure")
		return "; ".join(parts)

	@staticmethod
	def _iam_error_redirect(code: str) -> ApiResponse:
		return ApiResponse(302, {}, {"Location": f"/app/?login_error={code}"})

	def _iam_login_redirect(self) -> ApiResponse:
		if self.auth_mode != AUTH_MODE_IAM or self.iam_config is None:
			return _error(404, "route_not_found", "The API route was not found.")
		state = new_iam_state(self.iam_config.client_secret)
		return ApiResponse(
			302,
			{},
			{
				"Location": build_iam_authorize_url(self.iam_config, state),
				"Set-Cookie": self._iam_state_cookie(state),
			},
		)

	def _iam_callback(self, query: str, headers: Mapping[str, str]) -> ApiResponse:
		if self.auth_mode != AUTH_MODE_IAM or self.iam_config is None or self.iam_client is None:
			return _error(404, "route_not_found", "The API route was not found.")
		parameters = parse_qs(query)
		code = parameters.get("code", [""])[0]
		state = parameters.get("state", [""])[0]
		cookie_state = parse_cookies(headers.get("cookie")).get(IAM_STATE_COOKIE_NAME, "")
		clear_state = self._iam_state_cookie("", max_age=0)
		if not code or not state or state != cookie_state or not verify_iam_state(state, self.iam_config.client_secret):
			response = self._iam_error_redirect("invalid_state")
			response.headers["Set-Cookie"] = clear_state
			return response
		try:
			token = self.iam_client.exchange_code(code)
			profile = self.iam_client.fetch_user(str(token["access_token"]))
		except Exception:
			response = self._iam_error_redirect("iam_exchange_failed")
			response.headers["Set-Cookie"] = clear_state
			return response
		user, denied = self._complete_login(profile["email"].strip().lower(), profile.get("display_name", ""))
		if denied is not None:
			response = self._iam_error_redirect(str(denied.body["error"]["code"]))
			response.headers["Set-Cookie"] = clear_state
			return response
		session_id = new_session_id()
		self.repository.create_session(hash_secret(session_id), int(user["id"]), session_expiry())
		self.repository.touch_user_login(int(user["id"]))
		return ApiResponse(
			302,
			{},
			{
				"Location": "/app/",
				"Set-Cookie": self._session_cookie(session_id),
			},
		)

	def _manage_tokens(self, method: str, path: str, identity: Identity, body: bytes) -> ApiResponse:
		if identity.user_id is None:
			return _error(400, "tokens_unsupported", "API tokens require a signed-in account.")
		if path == "/api/v1/tokens":
			if method == "GET":
				return ApiResponse(200, {"items": self.repository.list_api_tokens(identity.user_id)})
			if method != "POST":
				return _error(405, "method_not_allowed", "Only GET and POST are allowed.")
			try:
				payload = json.loads(body.decode("utf-8")) if body else {}
			except (UnicodeDecodeError, json.JSONDecodeError):
				return _error(400, "invalid_json", "The request body is not valid UTF-8 JSON.")
			if not isinstance(payload, dict):
				return _error(422, "invalid_token_request", "The request body must be an object.")
			name = payload.get("name", "")
			if not isinstance(name, str) or len(name.strip()) > 100:
				return _error(422, "invalid_token_request", "name must be a string of at most 100 characters.")
			plaintext = new_api_token()
			item = self.repository.create_api_token(identity.user_id, name.strip(), hash_secret(plaintext))
			return ApiResponse(201, {"token": plaintext, "item": item})
		suffix = path[len("/api/v1/tokens/"):]
		parts = suffix.split("/")
		if len(parts) != 2 or parts[1] != "revoke" or not parts[0].isdigit():
			return _error(404, "route_not_found", "The API route was not found.")
		if method != "POST":
			return _error(405, "method_not_allowed", "Only POST is allowed.")
		if not self.repository.revoke_api_token(int(parts[0]), identity.user_id):
			return _error(404, "token_not_found", "The API token was not found.")
		return ApiResponse(200, {"result": "revoked"})

	def _manage_users(self, method: str, path: str, identity: Identity, body: bytes) -> ApiResponse:
		denied = self._require_admin(identity)
		if denied is not None:
			return denied
		if path == "/api/v1/admin/users":
			if method == "GET":
				return ApiResponse(200, {"items": self.repository.list_users()})
			if method != "POST":
				return _error(405, "method_not_allowed", "Only GET and POST are allowed.")
			try:
				payload = json.loads(body.decode("utf-8"))
			except (UnicodeDecodeError, json.JSONDecodeError):
				return _error(400, "invalid_json", "The request body is not valid UTF-8 JSON.")
			if not isinstance(payload, dict):
				return _error(422, "invalid_user_request", "The request body must be an object.")
			email = payload.get("email")
			role = payload.get("role", "member")
			display_name = payload.get("display_name", "")
			if not isinstance(email, str) or not EMAIL_PATTERN.fullmatch(email.strip()):
				return _error(422, "invalid_user_request", "A valid email address is required.")
			if role not in {"admin", "member"}:
				return _error(422, "invalid_user_request", "role must be admin or member.")
			if not isinstance(display_name, str) or len(display_name.strip()) > 100:
				return _error(422, "invalid_user_request", "display_name must be a string of at most 100 characters.")
			email = email.strip().lower()
			if self.repository.get_user_by_email(email) is not None:
				return _error(409, "user_exists", "The user already exists.")
			user = self.repository.create_user(email, display_name.strip(), role)
			return ApiResponse(201, {"user": user})
		suffix = path[len("/api/v1/admin/users/"):]
		if not suffix.isdigit():
			return _error(404, "route_not_found", "The API route was not found.")
		target_id = int(suffix)
		target = self.repository.get_user_by_id(target_id)
		if target is None:
			return _error(404, "user_not_found", "The user was not found.")
		if method == "PATCH":
			try:
				payload = json.loads(body.decode("utf-8"))
			except (UnicodeDecodeError, json.JSONDecodeError):
				return _error(400, "invalid_json", "The request body is not valid UTF-8 JSON.")
			if not isinstance(payload, dict):
				return _error(422, "invalid_user_request", "The request body must be an object.")
			role = payload.get("role")
			status = payload.get("status")
			if role is not None and role not in {"admin", "member"}:
				return _error(422, "invalid_user_request", "role must be admin or member.")
			if status is not None and status not in {"active", "disabled"}:
				return _error(422, "invalid_user_request", "status must be active or disabled.")
			if role is None and status is None:
				return _error(422, "invalid_user_request", "Nothing to update.")
			if identity.user_id == target_id and (role == "member" or status == "disabled"):
				return _error(400, "cannot_modify_self", "You cannot demote or disable your own account.")
			updated = self.repository.update_user(target_id, role=role, status=status)
			if status == "disabled":
				self.repository.disable_user_access(target_id)
			return ApiResponse(200, {"user": updated})
		if method == "DELETE":
			if identity.user_id == target_id:
				return _error(400, "cannot_modify_self", "You cannot remove your own account.")
			self.repository.update_user(target_id, status="disabled")
			self.repository.disable_user_access(target_id)
			return ApiResponse(200, {"result": "disabled"})
		return _error(405, "method_not_allowed", "Only PATCH and DELETE are allowed.")

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

	def _dashboard_activity(self, query: str) -> ApiResponse:
		parameters = parse_qs(query, keep_blank_values=True)
		if set(parameters) - {"days", "region", "region_code"} or any(
			len(values) != 1 for values in parameters.values()
		):
			return _error(400, "invalid_query", "The dashboard activity query contains unsupported parameters.")
		try:
			days = int(parameters.get("days", ["365"])[0])
		except ValueError:
			return _error(400, "invalid_query", "days must be an integer.")
		if not 1 <= days <= 730:
			return _error(400, "invalid_query", "days must be between 1 and 730.")
		region_code = parameters.get("region_code", parameters.get("region", [None]))[0]
		if region_code is not None:
			region_code = region_code.strip().upper()
			if region_code not in SUPPORTED_REGIONS:
				return _error(400, "invalid_query", f"Unsupported region_code: {region_code}")
		return ApiResponse(200, self.repository.activity_by_day(days, region_code))

	def _dashboard_rule_stats(self, query: str) -> ApiResponse:
		parameters = parse_qs(query, keep_blank_values=True)
		if set(parameters) - {"days", "region_code"} or any(
			len(values) != 1 for values in parameters.values()
		):
			return _error(400, "invalid_query", "The dashboard rule stats query contains unsupported parameters.")
		days: int | None = None
		if "days" in parameters:
			try:
				days = int(parameters["days"][0])
			except ValueError:
				return _error(400, "invalid_query", "days must be an integer.")
			if not 1 <= days <= 730:
				return _error(400, "invalid_query", "days must be between 1 and 730.")
		region_code = parameters.get("region_code", [None])[0]
		if region_code is not None:
			region_code = region_code.strip().upper()
			if region_code not in SUPPORTED_REGIONS:
				return _error(400, "invalid_query", f"Unsupported region_code: {region_code}")
		return ApiResponse(200, self.repository.rule_trigger_stats(days, region_code))

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
		for key in ("received_from", "received_to"):
			value = parameters.get(key, [None])[0]
			if value is None:
				filters[key] = None
				continue
			parsed_date = _parse_date_filter(value.strip())
			if parsed_date is None:
				return _error(400, "invalid_query", f"Invalid {key} filter; expected YYYY-MM-DD.")
			filters[key] = parsed_date
		if (
			filters["received_from"] is not None
			and filters["received_to"] is not None
			and filters["received_from"] > filters["received_to"]
		):
			return _error(400, "invalid_query", "received_from must not be after received_to.")
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
		*,
		actor: str,
	) -> ApiResponse:
		parts = suffix.split("/")
		if len(parts) != 2 or parts[1] not in {"soft-delete", "restore", "review-confirm"}:
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
		if parts[1] == "review-confirm":
			note = payload.get("note")
			if note is not None and (not isinstance(note, str) or len(note.strip()) > 500):
				return _error(
					422,
					"invalid_management_request",
					"note must be a string of at most 500 characters.",
				)
			try:
				review = self.repository.confirm_archive_review(
					package_id,
					actor=actor,
					note=note.strip() if isinstance(note, str) and note.strip() else None,
				)
			except ArchiveConflict as conflict:
				status = 404 if conflict.code == "archive_not_found" else 409
				return _error(status, conflict.code, str(conflict))
			return ApiResponse(
				200,
				{
					"result": review["result"],
					"review": {key: value for key, value in review.items() if key != "result"},
				},
				{"Idempotency-Replayed": "true"} if review["result"] == "replayed" else {},
			)
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
					actor=actor,
					reason=reason.strip(),
					replacement_package_id=replacement_package_id,
				)
				result = "deleted"
			else:
				event = self.repository.restore_archive(
					package_id,
					actor=actor,
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
		*,
		actor: str,
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
				actor=actor,
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
		if action is not None and action not in {"delete", "restore", "baseline_set", "review_confirm"}:
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

