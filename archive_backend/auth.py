from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:
	from .repository import ArchiveRepository

AUTH_MODE_NONE = "none"
AUTH_MODE_LEGACY_TOKEN = "legacy-token"
AUTH_MODE_GOOGLE = "google"

SESSION_COOKIE_NAME = "aov_session"
SESSION_TTL = timedelta(days=7)
API_TOKEN_PREFIX = "aov_pk_"


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

	if auth_mode == AUTH_MODE_GOOGLE:
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
