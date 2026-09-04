from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from svn_cli_log_auth import decode_svn_console_output, fetch_svn_log_with_auth


class SvnConsoleDecodeTests(unittest.TestCase):
	def test_decodes_utf8_output(self) -> None:
		value = "M /Xml/Garena/TW/CommonCore/日常活动表.dtxml".encode("utf-8")
		self.assertIn("日常活动表.dtxml", decode_svn_console_output(value))

	def test_falls_back_to_windows_chinese_output(self) -> None:
		value = "M /Xml/Garena/TW/CommonCore/日常活动表.dtxml".encode("gb18030")
		self.assertIn("日常活动表.dtxml", decode_svn_console_output(value))

	def test_fetch_uses_xml_to_preserve_repository_path_encoding(self) -> None:
		xml = "<?xml version='1.0' encoding='UTF-8'?><log><logentry revision='10'><paths><path action='M'>/日常活动表.dtxml</path></paths></logentry></log>"
		completed = SimpleNamespace(returncode=0, stdout=xml.encode("utf-8"), stderr=b"")
		with patch("svn_cli_log_auth.subprocess.run", return_value=completed) as run:
			result = fetch_svn_log_with_auth(
				svn_target="http://example.test/repo",
				current_revision_spec="r10",
			)

		self.assertIn("--xml", run.call_args.args[0])
		self.assertIn("日常活动表.dtxml", result.stdout)


if __name__ == "__main__":
	unittest.main()
