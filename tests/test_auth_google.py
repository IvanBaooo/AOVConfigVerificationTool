from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from archive_backend.api import ArchiveApplication
from archive_backend.auth import hash_secret
from archive_backend.repository import ArchiveRepository
from archive_backend.schema_validation import ArchivePayloadValidator


class FakeGoogleVerifier:
	def __init__(self, profiles: dict[str, dict[str, str]]) -> None:
		self.profiles = profiles

	def verify(self, credential: str) -> dict[str, str]:
		profile = self.profiles.get(credential)
		if profile is None:
			raise ValueError("invalid credential")
		return profile


class GoogleAuthTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		self.repository = ArchiveRepository(Path(self.temp_dir.name) / "archives.sqlite3")
		self.application = ArchiveApplication(
			repository=self.repository,
			validator=ArchivePayloadValidator(),
			access_token=None,
			auth_mode="google",
			google_verifier=FakeGoogleVerifier({
				"admin-cred": {"email": "Boss@Example.com", "display_name": "Boss"},
				"member-cred": {"email": "member@example.com", "display_name": "Member"},
			}),
		)

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def login(self, credential: str):
		return self.application.handle(
			"POST",
			"/api/v1/auth/google",
			{"Content-Type": "application/json"},
			json.dumps({"credential": credential}).encode("utf-8"),
		)

	@staticmethod
	def session_cookie(response) -> str:
		set_cookie = response.headers.get("Set-Cookie", "")
		return set_cookie.split(";", 1)[0]

	def me(self, cookie: str):
		return self.application.handle("GET", "/api/v1/auth/me", {"Cookie": cookie})

	def test_first_login_bootstraps_admin_and_sets_session_cookie(self) -> None:
		response = self.login("admin-cred")

		self.assertEqual(200, response.status)
		self.assertEqual("admin", response.body["user"]["role"])
		self.assertEqual("boss@example.com", response.body["user"]["email"])
		set_cookie = response.headers["Set-Cookie"]
		self.assertIn("aov_session=", set_cookie)
		self.assertIn("HttpOnly", set_cookie)

		me = self.me(self.session_cookie(response))
		self.assertEqual(200, me.status)
		self.assertEqual("boss@example.com", me.body["user"]["email"])
		self.assertEqual("google", me.body["auth_mode"])

	def test_second_user_is_rejected_until_whitelisted(self) -> None:
		self.login("admin-cred")

		rejected = self.login("member-cred")
		self.assertEqual(403, rejected.status)
		self.assertEqual("not_in_whitelist", rejected.body["error"]["code"])

		created = self.application.handle(
			"POST",
			"/api/v1/admin/users",
			{"Cookie": self.session_cookie(self.login("admin-cred")), "Content-Type": "application/json"},
			json.dumps({"email": "member@example.com"}).encode("utf-8"),
		)
		self.assertEqual(201, created.status)

		accepted = self.login("member-cred")
		self.assertEqual(200, accepted.status)
		self.assertEqual("member", accepted.body["user"]["role"])

	def test_invalid_credential_and_missing_body_are_rejected(self) -> None:
		bad = self.login("unknown-cred")
		self.assertEqual(401, bad.status)
		self.assertEqual("invalid_google_token", bad.body["error"]["code"])

		empty = self.application.handle(
			"POST",
			"/api/v1/auth/google",
			{"Content-Type": "application/json"},
			b"{}",
		)
		self.assertEqual(422, empty.status)

	def test_disabled_account_cannot_login(self) -> None:
		admin_cookie = self.session_cookie(self.login("admin-cred"))
		created = self.application.handle(
			"POST",
			"/api/v1/admin/users",
			{"Cookie": admin_cookie, "Content-Type": "application/json"},
			json.dumps({"email": "member@example.com"}).encode("utf-8"),
		)
		user_id = created.body["user"]["id"]
		self.application.handle(
			"PATCH",
			f"/api/v1/admin/users/{user_id}",
			{"Cookie": admin_cookie, "Content-Type": "application/json"},
			json.dumps({"status": "disabled"}).encode("utf-8"),
		)

		rejected = self.login("member-cred")
		self.assertEqual(403, rejected.status)
		self.assertEqual("account_disabled", rejected.body["error"]["code"])

	def test_logout_invalidates_session(self) -> None:
		cookie = self.session_cookie(self.login("admin-cred"))
		self.assertEqual(200, self.me(cookie).status)

		logout = self.application.handle("POST", "/api/v1/auth/logout", {"Cookie": cookie})
		self.assertEqual(200, logout.status)
		self.assertIn("Max-Age=0", logout.headers["Set-Cookie"])
		self.assertEqual(401, self.me(cookie).status)

	def test_expired_session_is_rejected(self) -> None:
		self.login("admin-cred")
		user = self.repository.get_user_by_email("boss@example.com")
		self.repository.create_session(hash_secret("stale-session"), user["id"], "2000-01-01T00:00:00+00:00")

		self.assertEqual(401, self.me("aov_session=stale-session").status)

	def test_requests_without_credentials_are_rejected(self) -> None:
		response = self.application.handle("GET", "/api/v1/package-archives", {})
		self.assertEqual(401, response.status)


if __name__ == "__main__":
	unittest.main()
