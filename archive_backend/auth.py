from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Mapping
from urllib.parse import urlencode

if TYPE_CHECKING:
	from .repository import ArchiveRepository

AUTH_MODE_NONE = "none"
AUTH_MODE_LEGACY_TOKEN = "legacy-token"
AUTH_MODE_GOOGLE = "google"
AUTH_MODE_IAM = "iam"

SESSION_COOKIE_NAME = "aov_session"
SESSION_TTL = timedelta(days=7)
API_TOKEN_PREFIX = "aov_pk_"

IAM_DEFAULT_BASE_URL = "https://tn.gsp.garenanow.com"
IAM_STATE_COOKIE_NAME = "aov_iam_state"
IAM_STATE_TTL_SECONDS = 600


def _utc_now() -> datetime:
	return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
	return moment.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def hash_secret(value: str) -> str:
	return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_session_id() -> str:
	return secrets.token_hex(32)


def new_api_token() -> str:
	return API_TOKEN_PREFIX + secrets.token_hex(24)


def session_expiry() -> str:
	return _iso(_utc_now() + SESSION_TTL)


def parse_cookies(header: str | None) -> dict[str, str]:
	cookies: dict[str, str] = {}
	if not header:
		return cookies
	for part in header.split(";"):
		name, separator, value = part.strip().partition("=")
		if separator:
			cookies[name.strip()] = value.strip()
	return cookies


@dataclass(frozen=True)
class Identity:
	email: str
	display_name: str
	role: str
	source: str
	user_id: int | None = None
	token_id: int | None = None

	@property
	def is_admin(self) -> bool:
		return self.role == "admin"


class GoogleIdTokenVerifier:
	def __init__(self, client_id: str) -> None:
		self.client_id = client_id

	def verify(self, credential: str) -> dict[str, str]:
		from google.auth.transport import requests as google_requests
		from google.oauth2 import id_token as google_id_token

		payload = google_id_token.verify_oauth2_token(
			credential,
			google_requests.Request(),
			self.client_id,
		)
		email = str(payload.get("email") or "")
		if not email or payload.get("email_verified") is False:
			raise ValueError("The Google account email is missing or unverified.")
		return {"email": email, "display_name": str(payload.get("name") or "")}


@dataclass(frozen=True)
class IamConfig:
	client_id: str
	client_secret: str
	redirect_uri: str
	signout_redirect_uri: str
	base_url: str = IAM_DEFAULT_BASE_URL


def build_iam_authorize_url(config: IamConfig, state: str) -> str:
	query = urlencode({
		"response_type": "code",
		"client_id": config.client_id,
		"redirect_uri": config.redirect_uri,
		"scope": "profile",
		"state": state,
	})
	return f"{config.base_url}/bacchus/sso/v1/auth?{query}"


def build_iam_signout_url(config: IamConfig) -> str:
	query = urlencode({
		"client_id": config.client_id,
		"redirect_uri": config.signout_redirect_uri,
	})
	return f"{config.base_url}/bacchus/sso/v1/sign_out?{query}"


def new_iam_state(secret: str) -> str:
	nonce = secrets.token_hex(16)
	expiry = str(int(_utc_now().timestamp()) + IAM_STATE_TTL_SECONDS)
	signature = hmac.new(secret.encode("utf-8"), f"{nonce}.{expiry}".encode("utf-8"), hashlib.sha256).hexdigest()
	return f"{nonce}.{expiry}.{signature}"


def verify_iam_state(state: str, secret: str) -> bool:
	parts = state.split(".")
	if len(parts) != 3:
		return False
	nonce, expiry, signature = parts
	expected = hmac.new(secret.encode("utf-8"), f"{nonce}.{expiry}".encode("utf-8"), hashlib.sha256).hexdigest()
	if not hmac.compare_digest(signature, expected):
		return False
	try:
		return int(expiry) >= int(_utc_now().timestamp())
	except ValueError:
		return False


class IamClient:
	"""Bacchus SSO 的 S2S 调用；_post 可注入替换以便测试。"""

	def __init__(self, config: IamConfig) -> None:
		self.config = config

	def _post(self, path: str, payload: Mapping[str, object], bearer: str | None = None) -> dict[str, object]:
		request = urllib.request.Request(
			f"{self.config.base_url}{path}",
			data=json.dumps(dict(payload)).encode("utf-8"),
			headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {bearer}"} if bearer else {})},
			method="POST",
		)
		with urllib.request.urlopen(request, timeout=15) as response:
			return json.loads(response.read().decode("utf-8"))

	@staticmethod
	def _result(payload: Mapping[str, object]) -> Mapping[str, object]:
		if int(payload.get("code", -1)) != 0:
			raise ValueError(f"IAM S2S error: {payload.get('message') or payload.get('code')}")
		result = payload.get("result")
		if not isinstance(result, Mapping):
			raise ValueError("IAM S2S response is missing the result object.")
		return result

	def exchange_code(self, code: str) -> Mapping[str, object]:
		payload = self._post("/bacchus/sso/s2s/v1/token", {
			"grant_type": "authorization_code",
			"client_id": self.config.client_id,
			"client_secret": self.config.client_secret,
			"code": code,
		})
		result = self._result(payload)
		if not result.get("access_token"):
			raise ValueError("IAM token exchange returned no access token.")
		return result

	def fetch_user(self, access_token: str) -> dict[str, str]:
		payload = self._post("/bacchus/sso/s2s/v1/user/info", {}, bearer=access_token)
		result = self._result(payload)
		email = str(result.get("email") or "").strip().lower()
		if not email:
			raise ValueError("IAM user info returned no email.")
		display_name = str(result.get("name") or result.get("username") or email.split("@")[0])
		return {"email": email, "display_name": display_name, "user_id": str(result.get("user_id") or "")}


def _identity_from_user(user: Mapping[str, object], source: str) -> Identity | None:
	if user.get("status") != "active":
		return None
	return Identity(
		email=str(user["email"]),
		display_name=str(user.get("display_name") or ""),
		role=str(user.get("role") or "member"),
		source=source,
		user_id=int(user["id"]),
		token_id=int(user["token_id"]) if user.get("token_id") is not None else None,
	)


def resolve_identity(
	repository: "ArchiveRepository",
	auth_mode: str,
	legacy_token: str | None,
	headers: Mapping[str, str],
) -> Identity | None:
	if auth_mode == AUTH_MODE_NONE:
		return Identity(email="local-dev", display_name="本地调试", role="admin", source="none")

	if auth_mode == AUTH_MODE_LEGACY_TOKEN and legacy_token:
		authorization = headers.get("authorization", "")
		expected = f"Bearer {legacy_token}"
		if hmac.compare_digest(authorization.encode("utf-8"), expected.encode("utf-8")):
			return Identity(email="legacy-token", display_name="旧版令牌", role="admin", source="legacy")
		return None

	if auth_mode in {AUTH_MODE_GOOGLE, AUTH_MODE_IAM}:
		session_id = parse_cookies(headers.get("cookie")).get(SESSION_COOKIE_NAME)
		if session_id:
			user = repository.get_session_user(
				hash_secret(session_id),
				slide_to=session_expiry(),
			)
			if user is not None:
				return _identity_from_user(user, "session")
		authorization = headers.get("authorization", "")
		if authorization.startswith("Bearer "):
			presented = authorization[len("Bearer "):]
			if presented.startswith(API_TOKEN_PREFIX):
				user = repository.get_token_user(hash_secret(presented))
				if user is not None:
					return _identity_from_user(user, "api-token")
	return None
