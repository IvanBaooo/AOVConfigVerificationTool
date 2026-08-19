from __future__ import annotations

import unittest

from svn_commit_validation_optimized import run_commit_record_check_optimized
from svn_path_policy import (
	describe_svn_path,
	parse_whitelist_patterns,
	path_matches_whitelist,
)


class SvnPathPolicyTests(unittest.TestCase):
	def test_known_generated_xml_uses_readable_business_table_name(self) -> None:
		description = describe_svn_path(
			"/Taiwan/Databin/Server/Shop/SvrHeroSkinShop.xml"
		)

		self.assertEqual("皮肤", description["module"])
		self.assertEqual("英雄皮肤促销表", description["table_name"])
		self.assertEqual(
			"英雄皮肤促销表 / SvrHeroSkinShop.xml",
			description["readable_name"],
		)
		self.assertEqual("built_in", description["mapping_source"])

	def test_unknown_file_falls_back_to_file_stem_and_keeps_directory(self) -> None:
		description = describe_svn_path(
			"/Thailand/Databin/Server/Shop/SvrMysterySale.xml"
		)

		self.assertEqual("SvrMysterySale", description["table_name"])
		self.assertEqual("SvrMysterySale / SvrMysterySale.xml", description["readable_name"])
		self.assertEqual("/Thailand/Databin/Server/Shop", description["directory"])
		self.assertEqual("file_name", description["mapping_source"])

	def test_web_supplied_mapping_can_override_builtin_mapping(self) -> None:
		description = describe_svn_path(
			"/Taiwan/Databin/Server/Shop/SvrHeroSkinShop.xml",
			[{
				"path_suffix": "/Databin/Server/Shop/SvrHeroSkinShop.xml",
				"module": "商城",
				"table_name": "网页规则中的皮肤表",
			}],
		)

		self.assertEqual("商城", description["module"])
		self.assertEqual("网页规则中的皮肤表", description["table_name"])
		self.assertEqual("configured", description["mapping_source"])

	def test_whitelist_parser_accepts_lines_punctuation_comments_and_deduplicates(self) -> None:
		patterns = parse_whitelist_patterns(
			"Hero_MD5*.txt\n# 说明\n/Taiwan/Shop/A.xml，/Taiwan/Shop/A.xml；B.xml"
		)

		self.assertEqual(
			["/Hero_MD5*.txt", "/Taiwan/Shop/A.xml", "/B.xml"],
			patterns,
		)

	def test_whitelist_supports_basename_glob_exact_path_and_explicit_directory(self) -> None:
		path = "/Taiwan/Databin/Server/Actor/Hero_MD5_01.txt"

		self.assertTrue(path_matches_whitelist(path, "Hero_MD5*.txt"))
		self.assertTrue(path_matches_whitelist(path, path))
		self.assertTrue(path_matches_whitelist(path, "/Taiwan/Databin/Server/Actor/"))
		self.assertFalse(path_matches_whitelist(path, "/Thailand/Databin/Server/Actor/"))

	def test_whitelisted_change_is_audited_with_readable_table_name(self) -> None:
		svn_log = """\
r102 | tester | 2026-07-27 |
Changed paths:
   M /repo/Tools/TdrTable/ServerBytes/Taiwan/Databin/Server/Shop/Current.xml

r101 | tester | 2026-07-27 |
Changed paths:
   M /repo/Tools/TdrTable/ServerBytes/Taiwan/Databin/Server/Shop/SvrHeroSkinShop.xml
"""
		result = run_commit_record_check_optimized(
			fixed_paths=["/Taiwan/Databin/Server/Shop/Current.xml"],
			validation_config={
				"commit_record": {
					"enabled": True,
					"input_method": "revision_spec",
					"last_external_revision_spec": "r100",
					"current_revision_spec": "r102",
					"scope_roots": ["/Taiwan"],
					"svn_log_text": svn_log,
					"whitelist_paths": ["SvrHeroSkinShop.xml"],
				}
			},
		)

		self.assertEqual("passed", result["status"])
		self.assertEqual([], result["warnings"])
		self.assertEqual([], result["affected_tables"])
		self.assertEqual(1, len(result["ignored_changes"]))
		self.assertEqual("英雄皮肤促销表", result["ignored_tables"][0]["table_name"])
		ignored = result["ignored_changes"][0]
		self.assertEqual("英雄皮肤促销表", ignored["table_name"])
		self.assertEqual("ignored_by_whitelist", ignored["resolution"])
		self.assertEqual("/SvrHeroSkinShop.xml", ignored["whitelist_pattern"])

	def test_commit_report_uses_supplied_path_mapping(self) -> None:
		svn_log = """\
r201 | tester | 2026-07-27 |
Changed paths:
   M /repo/ServerBytes/Taiwan/Databin/Server/Event/SvrEvent.xml

r202 | tester | 2026-07-27 |
Changed paths:
   M /repo/ServerBytes/Taiwan/Databin/Server/Event/Current.xml
"""
		result = run_commit_record_check_optimized(
			fixed_paths=["/Taiwan/Databin/Server/Event/Current.xml"],
			validation_config={
				"commit_record": {
					"enabled": True,
					"input_method": "revision_spec",
					"last_external_revision_spec": "r200",
					"current_revision_spec": "r202",
					"scope_roots": ["/Taiwan"],
					"svn_log_text": svn_log,
					"path_mappings": [{
						"path_suffix": "/Databin/Server/Event/SvrEvent.xml",
						"module": "活动",
						"table_name": "活动上架表",
					}],
				}
			},
		)

		self.assertEqual("warning", result["status"])
		self.assertEqual("活动上架表", result["warnings"][0]["table_name"])
		self.assertEqual("configured", result["warnings"][0]["mapping_source"])
		self.assertEqual("活动上架表", result["affected_tables"][0]["table_name"])

if __name__ == "__main__":
	unittest.main()
