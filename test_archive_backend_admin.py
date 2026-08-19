from __future__ import annotations

import http.client
import tempfile
import threading
import unittest
from pathlib import Path

from archive_backend.api import ArchiveApplication
from archive_backend.repository import ArchiveRepository
from archive_backend.schema_validation import ArchivePayloadValidator
from archive_backend.server import create_http_server


class ArchiveAdminHttpTests(unittest.TestCase):
	def setUp(self) -> None:
		self.temp_dir = tempfile.TemporaryDirectory()
		application = ArchiveApplication(
			repository=ArchiveRepository(Path(self.temp_dir.name) / "archives.sqlite3"),
			validator=ArchivePayloadValidator(),
			access_token="admin-test-token",
		)
		self.server = create_http_server(application, host="127.0.0.1", port=0)
		self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
		self.thread.start()

	def tearDown(self) -> None:
		self.server.shutdown()
		self.server.server_close()
		self.thread.join(timeout=5)
		self.temp_dir.cleanup()

	def request(self, method: str, path: str, headers: dict[str, str] | None = None):
		connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
		connection.request(method, path, headers=headers or {})
		response = connection.getresponse()
		body = response.read()
		response_headers = dict(response.getheaders())
		status = response.status
		connection.close()
		return status, response_headers, body

	def test_root_redirects_to_admin_interface(self) -> None:
		status, headers, body = self.request("GET", "/")
		self.assertEqual(status, 302)
		self.assertEqual(headers["Location"], "/admin/")
		self.assertEqual(body, b"")

	def test_admin_assets_are_public_and_hardened(self) -> None:
		index_status, index_headers, index = self.request("GET", "/admin/")
		js_status, js_headers, javascript = self.request("GET", "/admin/app.js")
		rules_js_status, rules_js_headers, rules_javascript = self.request("GET", "/admin/rules.js")
		css_status, css_headers, stylesheet = self.request("GET", "/admin/styles.css")
		rules_css_status, rules_css_headers, rules_stylesheet = self.request("GET", "/admin/rules.css")

		self.assertEqual(index_status, 200)
		self.assertIn("AOV 配置归档".encode("utf-8"), index)
		self.assertIn(b"Dashboard", index)
		self.assertIn(b'id="nav-dashboard"', index)
		self.assertIn(b'id="dashboard-view"', index)
		self.assertIn(b'class="admin-account"', index)
		self.assertIn("管理员 · 开发态".encode("utf-8"), index)
		self.assertIn(b'data-region="TW"', index)
		self.assertNotIn(b'id="filter-region"', index)
		self.assertNotIn(b'class="filter-bar"', index)
		self.assertIn(b'<select id="filter-version"', index)
		self.assertIn(b'<select id="filter-record-state"', index)
		self.assertIn(b'id="archive-action-dialog"', index)
		self.assertIn(b'id="archive-baseline-replacement"', index)
		self.assertIn(b'id="admin-audit-panel"', index)
		self.assertIn(b'id="audit-filter-action"', index)
		self.assertIn("管理员操作".encode("utf-8"), index)
		self.assertIn(b'<details class="rule-edit-section content-check-section" id="content-check-panel">', index)
		self.assertNotIn(b'<details class="rule-edit-section content-check-section" id="content-check-panel" open>', index)
		self.assertNotIn(b'<input id="filter-version"', index)
		archive_form_start = index.index(b'id="filter-form"')
		archive_thead_start = index.index(b"<thead>", archive_form_start)
		archive_thead_end = index.index(b"</thead>", archive_thead_start)
		self.assertLess(archive_thead_start, index.index(b'id="filter-version"'))
		self.assertLess(index.index(b'id="filter-version"'), archive_thead_end)
		self.assertEqual(index_headers["X-Content-Type-Options"], "nosniff")
		self.assertIn("frame-ancestors 'none'", index_headers["Content-Security-Policy"])
		self.assertEqual(js_status, 200)
		self.assertIn(b"loadArchives", javascript)
		self.assertIn(b"loadDashboard", javascript)
		self.assertIn(b"/api/v1/dashboard-summary", javascript)
		self.assertIn(b"activeRegion", javascript)
		self.assertIn(b"authRequired", javascript)
		self.assertIn(b"openArchiveActionDialog", javascript)
		self.assertIn(b"/api/v1/admin/package-archives/", javascript)
		self.assertIn(b"/api/v1/admin/release-baselines/", javascript)
		self.assertIn(b"loadAudit", javascript)
		self.assertIn(b"/api/v1/admin/archive-audit", javascript)
		self.assertTrue(js_headers["Content-Type"].startswith("text/javascript"))
		self.assertEqual(rules_js_status, 200)
		self.assertIn(b"loadRuleHistory", rules_javascript)
		self.assertIn(b"publishDraft", rules_javascript)
		self.assertIn(b"contentCount.textContent", rules_javascript)
		self.assertTrue(rules_js_headers["Content-Type"].startswith("text/javascript"))
		self.assertEqual(css_status, 200)
		self.assertIn(b".detail-drawer", stylesheet)
		self.assertTrue(css_headers["Content-Type"].startswith("text/css"))
		self.assertEqual(rules_css_status, 200)
		self.assertIn(b".rules-workspace", rules_stylesheet)
		self.assertTrue(rules_css_headers["Content-Type"].startswith("text/css"))

	def test_admin_does_not_weaken_api_authentication(self) -> None:
		status, _headers, body = self.request("GET", "/api/v1/package-archives")
		self.assertEqual(status, 401)
		self.assertIn(b"unauthorized", body)


if __name__ == "__main__":
	unittest.main()
