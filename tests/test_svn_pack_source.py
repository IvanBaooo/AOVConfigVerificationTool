import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from svn_pack_source import (
	PackSourceInspection,
	historical_pack_root,
	inspect_pack_source,
	_status_errors,
)


SVN_TEXT = "M /branches/release/Tools/TdrTable/ServerBytes/Taiwan/Databin/Server/Test.xml"


class Completed:
	def __init__(self, stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0):
		self.stdout = stdout
		self.stderr = stderr
		self.returncode = returncode


class PackSourceInspectionTests(unittest.TestCase):
	@patch("svn_pack_source._svn_info", return_value=(200, ""))
	def test_explicit_historical_mode_exports_old_revision(self, _info):
		inspection = inspect_pack_source(
			svn_text=SVN_TEXT,
			current_revision_spec="r150",
			content_mode="historical_revision",
			local_root=r"G:\TdrTable\ServerBytes",
			svn_target="http://example/ServerBytes",
		)
		self.assertTrue(inspection.historical)
		self.assertEqual(150, inspection.target_revision)
		self.assertIn("精确导出", inspection.warnings[0])

	@patch("svn_pack_source._check_selected_working_files", return_value=[])
	@patch(
		"svn_pack_source._svn_info",
		side_effect=[(200, ""), (200, "http://example/ServerBytes")],
	)
	def test_old_revision_defaults_to_checked_local_latest(self, _info, check):
		inspection = inspect_pack_source(
			svn_text=SVN_TEXT,
			current_revision_spec="r150",
			local_root=r"G:\TdrTable\ServerBytes",
			svn_target="http://example/ServerBytes",
		)
		self.assertFalse(inspection.historical)
		self.assertIn("Revision 仅用于选文件", inspection.warnings[0])
		check.assert_called_once()

	@patch("svn_pack_source._check_selected_working_files", return_value=[])
	@patch(
		"svn_pack_source._svn_info",
		side_effect=[(200, ""), (200, "http://example/ServerBytes")],
	)
	def test_head_revision_uses_clean_local_working_copy(self, _info, check):
		inspection = inspect_pack_source(
			svn_text=SVN_TEXT,
			current_revision_spec="r200",
			local_root=r"G:\TdrTable\ServerBytes",
			svn_target="http://example/ServerBytes",
		)
		self.assertEqual("local_latest", inspection.mode)
		self.assertEqual([], inspection.errors)
		check.assert_called_once()

	@patch("svn_pack_source._check_selected_working_files", return_value=["本地文件不是仓库最新版本：Test.xml"])
	@patch(
		"svn_pack_source._svn_info",
		side_effect=[(200, ""), (200, "http://example/ServerBytes")],
	)
	def test_latest_mode_reports_outdated_selected_file(self, _info, _check):
		inspection = inspect_pack_source(
			svn_text=SVN_TEXT,
			current_revision_spec="r200",
			local_root=r"G:\TdrTable\ServerBytes",
			svn_target="http://example/ServerBytes",
		)
		self.assertEqual(1, len(inspection.errors))

	def test_status_parser_rejects_local_and_repository_changes(self):
		xml = """<status><target path='x'>
		<entry path='local.xml'><wc-status item='modified' revision='10'/></entry>
		<entry path='old.xml'><wc-status item='normal' revision='10'/><repos-status item='modified'/></entry>
		<entry path='switched.xml'><wc-status item='normal' revision='10' switched='true'/></entry>
		</target></status>"""
		errors = _status_errors(xml)
		self.assertEqual(3, len(errors))
		self.assertTrue(any("状态异常" in value for value in errors))
		self.assertTrue(any("不是仓库最新" in value for value in errors))
		self.assertTrue(any("switched" in value for value in errors))


class HistoricalExportTests(unittest.TestCase):
	def test_historical_export_reuses_immutable_snapshot_cache(self):
		inspection = PackSourceInspection(
			mode="historical_revision",
			target_revision=150,
			head_revision=200,
			selected_file_count=1,
			local_root=r"G:\TdrTable\ServerBytes",
		)
		with tempfile.TemporaryDirectory() as temporary_directory:
			cache_root = Path(temporary_directory) / "cache"
			with patch("svn_pack_source._run", return_value=Completed(stdout=b"revision-150")) as run:
				with historical_pack_root(
					inspection,
					svn_text=SVN_TEXT,
					svn_target="http://example/ServerBytes",
					cache_root=cache_root,
				) as (root, stats):
					content = Path(root, "Taiwan", "Databin", "Server", "Test.xml").read_bytes()
					self.assertEqual(b"revision-150", content)
					self.assertEqual(1, stats["download_count"])
				with historical_pack_root(
					inspection,
					svn_text=SVN_TEXT,
					svn_target="http://example/ServerBytes",
					cache_root=cache_root,
				) as (root, stats):
					self.assertTrue(Path(root, "Taiwan", "Databin", "Server", "Test.xml").is_file())
					self.assertEqual(1, stats["cache_hit_count"])
				self.assertEqual(1, run.call_count)


if __name__ == "__main__":
	unittest.main()
