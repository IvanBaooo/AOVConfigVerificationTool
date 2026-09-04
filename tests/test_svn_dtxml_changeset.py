from __future__ import annotations

import unittest

from svn_dtxml_changeset import (
	build_dtxml_changeset,
	encode_svn_url,
	diff_dtxml_snapshots,
	infer_tdr_svn_target,
	parse_dtxml_snapshot,
	parse_repository_changed_paths,
	resolve_changed_path_url,
)


REPOSITORY_PATH = (
	"/HON_proj/branches/PUB/Beta54/Tools/TdrTable/"
	"Xml/Garena/TW/CommonCore/英雄皮肤促销表.dtxml"
)


def dtxml(rows: list[dict[str, str]], sheet: str = "svr下发皮肤促销特卖") -> bytes:
	columns = ["促销特卖ID", "皮肤ID", "点券价格", "上架时间"]
	column_xml = "".join(f'<Column Name="{name}" Type="System.String" />' for name in columns)
	row_xml = "".join(
		"<Row>" + "".join(
			f'<Cell Name="{name}">{value}</Cell>' for name, value in row.items() if value != ""
		) + "</Row>"
		for row in rows
	)
	return (
		'<?xml version="1.0" encoding="utf-8"?>'
		f'<Root Schema="Test"><Sheet Name="{sheet}"><Columns>{column_xml}</Columns>{row_xml}</Sheet></Root>'
	).encode("utf-8")


def dtxml_dynamic(rows: list[dict[str, str]], sheet: str) -> bytes:
	columns = list(dict.fromkeys(name for row in rows for name in row))
	column_xml = "".join(f'<Column Name="{name}" Type="System.String" />' for name in columns)
	row_xml = "".join(
		"<Row>" + "".join(f'<Cell Name="{name}">{value}</Cell>' for name, value in row.items()) + "</Row>"
		for row in rows
	)
	return (
		'<?xml version="1.0" encoding="utf-8"?>'
		f'<Root Schema="Test"><Sheet Name="{sheet}"><Columns>{column_xml}</Columns>{row_xml}</Sheet></Root>'
	).encode("utf-8")


def text_log(*revisions: tuple[int, str, str]) -> str:
	parts = []
	for revision, action, path in revisions:
		parts.extend([
			"------------------------------------------------------------------------",
			f"r{revision} | user | 2026-01-01 | 1 line",
			"Changed paths:",
			f"   {action} {path}",
			"",
			"message",
		])
	return "\n".join(parts)


class SvnDtxmlChangeSetTests(unittest.TestCase):
	def test_svn_url_encodes_chinese_path_as_utf8(self) -> None:
		url = "http://example.test/Tools/TdrTable/Xml/英雄皮肤促销表.dtxml"
		encoded = encode_svn_url(url)
		self.assertIn("%E8%8B%B1%E9%9B%84", encoded)
		self.assertNotIn("英雄", encoded)
		self.assertEqual(encoded, encode_svn_url(encoded))

	def test_tdr_target_and_changed_path_url_are_resolved_from_serverbytes_target(self) -> None:
		target = "http://example.test/repo/branches/Beta54/Tools/TdrTable/ServerBytes/Taiwan"
		self.assertEqual(
			"http://example.test/repo/branches/Beta54/Tools/TdrTable",
			infer_tdr_svn_target(target),
		)
		self.assertEqual(
			"http://example.test/repo/branches/Beta54/Tools/TdrTable/Xml/Garena/TW/CommonCore/英雄皮肤促销表.dtxml",
			resolve_changed_path_url(target, REPOSITORY_PATH),
		)

	def test_repository_log_parser_keeps_dtxml_paths_outside_serverbytes(self) -> None:
		parsed = parse_repository_changed_paths(text_log((100, "A", REPOSITORY_PATH + " (from /old/file.dtxml:99)")))
		self.assertEqual(1, len(parsed))
		self.assertEqual(REPOSITORY_PATH, parsed[0].path)

	def test_structural_diff_uses_sheet_key_and_reports_field_values(self) -> None:
		before = parse_dtxml_snapshot(dtxml([{
			"促销特卖ID": "10001",
			"皮肤ID": "51001",
			"点券价格": "710",
			"上架时间": "20260101000000",
		}]))
		after = parse_dtxml_snapshot(dtxml([{
			"促销特卖ID": "10001",
			"皮肤ID": "51001",
			"点券价格": "570",
			"上架时间": "20260101000000",
		}]))
		events = diff_dtxml_snapshots(
			repository_path=REPOSITORY_PATH,
			revision=101,
			action="M",
			before=before,
			after=after,
		)
		self.assertEqual(1, len(events))
		self.assertEqual("促销特卖ID=10001", events[0]["business_key"]["display"])
		self.assertEqual([{
			"field": "点券价格",
			"before": "710",
			"after": "570",
		}], events[0]["changed_fields"])

	def test_selected_non_contiguous_revisions_are_diffed_individually(self) -> None:
		contents = {
			100: dtxml([{"促销特卖ID": "10001", "皮肤ID": "51001", "点券价格": "710"}]),
			101: dtxml([{"促销特卖ID": "10001", "皮肤ID": "51001", "点券价格": "570"}]),
			102: dtxml([{"促销特卖ID": "10001", "皮肤ID": "51001", "点券价格": "600"}]),
			103: dtxml([{"促销特卖ID": "10001", "皮肤ID": "51001", "点券价格": "500"}]),
		}
		calls: list[tuple[str, int]] = []

		def loader(path: str, revision: int) -> bytes:
			calls.append((path, revision))
			return contents[revision]

		result = build_dtxml_changeset(
			log_text=text_log((101, "M", REPOSITORY_PATH), (102, "M", REPOSITORY_PATH), (103, "M", REPOSITORY_PATH)),
			revision_spec="r101,r103",
			tdr_svn_target="http://example.test/repo/branches/Beta54/Tools/TdrTable",
			region_code="TW",
			content_loader=loader,
		)
		self.assertEqual("passed", result["status"])
		self.assertEqual([100, 101, 102, 103], sorted({revision for _, revision in calls}))
		self.assertEqual(1, result["summary"]["change_count"])
		change = result["changes"][0]
		self.assertEqual([101, 103], change["revisions"])
		self.assertTrue(change["has_external_intermediate_change"])
		self.assertEqual("710", change["events"][0]["before"]["点券价格"])
		self.assertEqual("570", change["events"][0]["after"]["点券价格"])
		self.assertEqual("600", change["events"][1]["before"]["点券价格"])
		self.assertEqual("500", change["events"][1]["after"]["点券价格"])

	def test_added_and_deleted_rows_are_preserved(self) -> None:
		contents = {
			199: dtxml([{"促销特卖ID": "1", "皮肤ID": "10", "点券价格": "100"}]),
			200: dtxml([
				{"促销特卖ID": "1", "皮肤ID": "10", "点券价格": "100"},
				{"促销特卖ID": "2", "皮肤ID": "20", "点券价格": "200"},
			]),
			201: dtxml([{"促销特卖ID": "2", "皮肤ID": "20", "点券价格": "200"}]),
		}
		result = build_dtxml_changeset(
			log_text=text_log((200, "M", REPOSITORY_PATH), (201, "M", REPOSITORY_PATH)),
			revision_spec="r200-r201",
			tdr_svn_target="http://example.test/repo/branches/Beta54/Tools/TdrTable",
			region_code="TW",
			content_loader=lambda _path, revision: contents[revision],
		)
		by_key = {change["business_key"]["display"]: change for change in result["changes"]}
		self.assertEqual("deleted", by_key["促销特卖ID=1"]["change_type"])
		self.assertEqual("added", by_key["促销特卖ID=2"]["change_type"])

	def test_other_region_dtxml_is_not_included(self) -> None:
		th_path = REPOSITORY_PATH.replace("/TW/", "/TH/")
		result = build_dtxml_changeset(
			log_text=text_log((300, "M", th_path)),
			revision_spec="r300",
			tdr_svn_target="http://example.test/repo/branches/Beta54/Tools/TdrTable",
			region_code="TW",
			content_loader=lambda _path, _revision: b"",
		)
		self.assertEqual("no_selected_dtxml_changes", result["reason"])
		self.assertEqual([], result["changes"])

	def test_explicit_composite_key_identifies_modified_row(self) -> None:
		before = dtxml_dynamic([
			{"活动ID": "10", "活动索引": "1", "奖励": "100"},
			{"活动ID": "10", "活动索引": "2", "奖励": "200"},
		], "兑换活动表")
		after = dtxml_dynamic([
			{"活动ID": "10", "活动索引": "1", "奖励": "100"},
			{"活动ID": "10", "活动索引": "2", "奖励": "300"},
		], "兑换活动表")
		events = diff_dtxml_snapshots(
			repository_path="/repo/日常活动表.dtxml",
			revision=10,
			action="M",
			before=parse_dtxml_snapshot(before),
			after=parse_dtxml_snapshot(after),
			key_mappings={"日常活动表.dtxml::兑换活动表": ["活动ID", "活动索引"]},
		)
		self.assertEqual(1, len(events))
		self.assertEqual("活动ID=10, 活动索引=2", events[0]["business_key"]["display"])

	def test_deferred_sheet_keeps_row_changes_without_semantic_analysis(self) -> None:
		path = REPOSITORY_PATH.rsplit("/", 1)[0] + "/deferred.dtxml"
		contents = {
			9: dtxml_dynamic([{"ID": "1", "Value": "old"}], "DeferredSheet"),
			10: dtxml_dynamic([{"ID": "1", "Value": "new"}], "DeferredSheet"),
		}
		result = build_dtxml_changeset(
			log_text=text_log((10, "M", path)),
			revision_spec="r10",
			tdr_svn_target="http://example.test/repo/Tools/TdrTable",
			region_code="TW",
			deferred_sheets=["deferred.dtxml::*"],
			content_loader=lambda _path, revision: contents[revision],
		)
		self.assertEqual("warning", result["status"])
		self.assertEqual(1, len(result["changes"]))
		self.assertEqual("modified", result["changes"][0]["change_type"])
		self.assertEqual("deferred", result["changes"][0]["semantic_analysis"]["status"])
		self.assertEqual(1, result["summary"]["deferred_change_count"])
		self.assertEqual(1, result["summary"]["deferred_row_change_count"])
		self.assertEqual("DeferredSheet", result["deferred_changes"][0]["sheet"])


if __name__ == "__main__":
	unittest.main()
