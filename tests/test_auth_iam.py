from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from archive_backend.api import ArchiveApplication
from archive_backend.auth import (
	IamConfig,
	new_iam_state,
	verify_iam_state,
)
from archive_backend.repository import ArchiveRepository
from archive_backend.schema_validation import ArchivePayloadValidator


class FakeIamClient:
	def __init__(self, profiles: dict[str, dict[str, str]], fail: bool = False) -> None:
		self.profiles = profiles
		self.fail = fail

	def exchange_code(self, code: str):
		if self.fail or code not in self.profiles:
			raise ValueError("exchange failed")
		return {"access_token": f"at-{code}"}

	def fetch_user(self, access_token: str):
		if self.fail:
			raise ValueError("userinfo failed")
		code = access_token.removeprefix("at-")
		return self.profiles[code]


CONFIG = IamConfig(
	client_id="SSTESTCLIENT",
	client_secret="test-secret",
	redirect_uri="https://aov.example.com/auth/callback",
	signout_redirect_uri="https://aov.example.com/app/",
)


class IamAuthTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		self.repository = ArchiveRepository(Path(self.temp_dir.name) / "archives.sqlite3")
		self.application = ArchiveApplication(
			repository=self.repository,
			validator=ArchivePayloadValidator(),
			access_token=None,
			auth_mode="iam",
			iam_config=CONFIG,
			iam_client=FakeIamClient({
				"code-admin": {"email": "Boss@Garena.com", "display_name": "Boss"},
				"code-member": {"email": "member@garena.com", "display_name": "Member"},
			}),
		)

	def tearDown(self) -> None:
		self.temp_dir.cleanup()

	def start_login(self):
		response = self.application.handle("GET", "/auth/iam/login", {})
		self.assertEqual(302, response.status)
		location = response.headers["Location"]
		state = parse_qs(urlsplit(location).query)["state"][0]
		cookie = response.headers["Set-Cookie"].split(";", 1)[0]
		return location, state, cookie

	def callback(self, code: str, state: str, cookie: str):
		return self.application.handle(
			"GET",
			f"/auth/callback?code={code}&state={state}",
			{"Cookie": cookie},
		)

	def test_login_redirects_to_iam_with_signed_state_cookie(self) -> None:
		location, state, cookie = self.start_login()

		self.assertTrue(location.startswith("https://tn.gsp.garenanow.com/bacchus/sso/v1/auth?"))
		query = parse_qs(urlsplit(location).query)
		self.assertEqual(["code"], query["response_type"])
		self.assertEqual(["SSTESTCLIENT"], query["client_id"])
		self.assertEqual(["https://aov.example.com/auth/callback"], query["redirect_uri"])
		self.assertTrue(verify_iam_state(state, "test-secret"))
		self.assertTrue(cookie.startswith("aov_iam_state="))

	def test_health_exposes_iam_signout_url(self) -> None:
		health = self.application.handle("GET", "/health", {})
		self.assertEqual("iam", health.body["auth_mode"])
		signout = health.body["iam_signout_url"]
		self.assertTrue(signout.startswith("https://tn.gsp.garenanow.com/bacchus/sso/v1/sign_out?"))
		self.assertIn("client_id=SSTESTCLIENT", signout)

	def test_first_login_bootstraps_admin_and_lands_on_admin_page(self) -> None:
		_, state, cookie = self.start_login()
		response = self.callback("code-admin", state, cookie)

		self.assertEqual(302, response.status)
		self.assertEqual("/app/", response.headers["Location"])
		set_cookie = response.headers["Set-Cookie"]
		self.assertIn("aov_session=", set_cookie)

		session_cookie = set_cookie.split(";", 1)[0]
		me = self.application.handle("GET", "/api/v1/auth/me", {"Cookie": session_cookie})
		self.assertEqual(200, me.status)
		self.assertEqual("boss@garena.com", me.body["user"]["email"])
		self.assertEqual("admin", me.body["user"]["role"])

	def test_second_user_is_rejected_until_whitelisted(self) -> None:
		_, state, cookie = self.start_login()
		self.callback("code-admin", state, cookie)

		_, state2, cookie2 = self.start_login()
		rejected = self.callback("code-member", state2, cookie2)
		self.assertEqual(302, rejected.status)
		self.assertEqual("/app/?login_error=not_in_whitelist", rejected.headers["Location"])

		admin_cookie = self.callback("code-admin", *self.start_login()[1:]).headers["Set-Cookie"].split(";", 1)[0]
		self.application.handle(
			"POST",
			"/api/v1/admin/users",
			{"Cookie": admin_cookie, "Content-Type": "application/json"},
			b'{"email": "member@garena.com"}',
		)
		_, state3, cookie3 = self.start_login()
		accepted = self.callback("code-member", state3, cookie3)
		self.assertEqual("/app/", accepted.headers["Location"])

	def test_callback_rejects_bad_or_missing_state(self) -> None:
		_, state, cookie = self.start_login()

		mismatched = self.callback("code-admin", "wrong.state.here", cookie)
		self.assertEqual("/app/?login_error=invalid_state", mismatched.headers["Location"])

		no_cookie = self.callback("code-admin", state, "")
		self.assertEqual("/app/?login_error=invalid_state", no_cookie.headers["Location"])

	def test_exchange_failure_redirects_with_error(self) -> None:
		_, state, cookie = self.start_login()
		response = self.callback("unknown-code", state, cookie)
		self.assertEqual("/app/?login_error=iam_exchange_failed", response.headers["Location"])

	def test_iam_routes_are_hidden_in_other_modes(self) -> None:
		application = ArchiveApplication(
			repository=self.repository,
			validator=ArchivePayloadValidator(),
			access_token=None,
			auth_mode="none",
		)
		self.assertEqual(404, application.handle("GET", "/auth/iam/login", {}).status)
		self.assertEqual(404, application.handle("GET", "/auth/callback?code=x&state=y", {}).status)

	def test_state_signature_and_expiry(self) -> None:
		state = new_iam_state("secret")
		self.assertTrue(verify_iam_state(state, "secret"))
		self.assertFalse(verify_iam_state(state, "other-secret"))
		self.assertFalse(verify_iam_state("garbage", "secret"))
		self.assertFalse(verify_iam_state("a.b", "secret"))


if __name__ == "__main__":
	unittest.main()
