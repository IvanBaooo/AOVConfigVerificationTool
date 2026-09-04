from __future__ import annotations


def sample_report() -> dict[str, object]:
	return {
		"schema_version": "0.1",
		"package_id": "sgame_TW_Beta54_20260713153524",
		"idempotency_key": "sgame_TW_Beta54_20260713153524",
		"created_at": "2026-07-13T15:35:24+08:00",
		"input": {
			"archive_root": "/sgame/gamedata",
			"region_filter": {
				"enabled": True,
				"region_code": "TW",
				"region_dir": "Taiwan",
				"original_count": 54,
				"included_count": 20,
				"excluded_count": 34,
				"excluded_unknown_count": 0,
				"excluded_by_region": {"Thailand": 2, "Vietnam": 2},
			},
			"svn_username": "must-not-leak",
			"svn_password": "must-not-leak",
			"svn_log_text": "must-not-leak",
		},
		"status": {
			"package_status": "success",
			"validation_status": "passed",
			"ftp_status": "not_required",
			"archive_status": "not_started",
			"mail_status": "not_required",
		},
		"package": {
			"name": "sgame_TW_Beta54_20260713153524.tar.gz",
			"md5": "a158b202c61906ad4adc97f88597ac74",
			"sha256": "e062d33a0820b392b1737372c63d9d1510cfca6d8684adc3540b7d85464315fe",
			"list_file": "sgame_TW_Beta54_20260713153524.list.txt",
			"md5_file": "sgame_TW_Beta54_20260713153524.md5.txt",
			"report_file": "sgame_TW_Beta54_20260713153524.report.json",
			"file_count": 20,
			"failed_count": 0,
			"skipped_count": 0,
		},
		"files": [
			{
				"action": "M",
				"fixed_path": "/Taiwan/Databin/Server/Shop/SvrSpecialSale.xml",
				"archive_path": "/sgame/gamedata/Taiwan/Databin/Server/Shop/SvrSpecialSale.xml",
				"raw_line": "M ServerBytes/Taiwan/Databin/Server/Shop/SvrSpecialSale.xml",
				"local_path": r"G:\Branches\secret\SvrSpecialSale.xml",
				"status": "packaged",
				"local_exists": True,
				"size": 39351,
				"mtime": "2026-07-07T17:02:01+08:00",
			},
		],
		"validation": {
			"summary": {
				"error_count": 0,
				"warning_count": 1,
				"confirm_count": 0,
				"skipped_count": 1,
			},
			"checks": {
				"commit_record": {
					"status": "warning",
					"input_method": "revision_spec",
					"last_external": {
						"time": "2026-07-01T10:00:00+08:00",
						"revision_spec": "r1698349",
						"revisions": [1698349],
					},
					"current_package": {
						"revision_spec": "r1699919,r1699997",
						"revisions": [1699919, 1699997],
						"package_path_count": 20,
					},
					"comparison": {
						"expected_revision_spec": "r1698350-r1699997",
						"included_revision_spec": "r1699919,r1699997",
						"excluded_revision_spec": "r1698350-r1699918,r1699920-r1699996",
						"scope_roots": ["/Taiwan"],
					},
					"warning_count": 1,
					"warnings": [
						{
							"type": "unpackaged_change_between_releases",
							"level": "warning",
							"table_name": "Hero_MD5",
							"readable_name": "Hero_MD5.txt",
							"directory": "/Taiwan/Databin/Server/Actor",
							"file_name": "Hero_MD5.txt",
							"fixed_path": "/Taiwan/Databin/Server/Actor/Hero_MD5.txt",
							"revisions": [1698418],
							"actions": ["M"],
							"message": "unpackaged readable table warning",
							"svn_username": "must-not-leak",
						},
					],
					"statistics": {
						"svn_log_returned_revision_count": 64,
						"svn_log_min_revision": 1698363,
						"svn_log_max_revision": 1699997,
						"filtered_unresolved_revision_count": 1584,
						"whitelisted_warning_count": 3,
						"whitelisted_paths": ["/Taiwan/Databin/Server/Actor/Hero_MD5.txt"],
					},
				},
				"hidden_item_listing": {
					"id": "hidden-item-tab",
					"name": "隐藏道具识别与单独标注",
					"tables": ["道具信息表"],
					"status": "passed",
					"item_count": 0,
					"warning_count": 0,
					"items": [],
					"warnings": [],
				},
				"skin_precheck": {
					"status": "skipped",
					"reason": "missing_check_window",
					"source": {
						"dtxml": r"G:\Branches\secret\skin.dtxml",
						"xml": r"G:\Branches\secret\skin.xml",
						"xml_exists": True,
						"main_sheet": "main",
						"promo_sheet": "promo",
					},
					"items": [],
					"warnings": [],
				},
			},
		},
		"naming": {
			"region_code": "TW",
			"package_version": "Beta54",
			"timestamp": "20260713153524",
		},
	}


def check_entry(payload: dict[str, object], check_type: str) -> dict[str, object]:
	"""从归档 payload 的 validation.checks 数组中按 type 取一条。"""
	for entry in payload["validation"]["checks"]:
		if entry["type"] == check_type:
			return entry
	raise AssertionError(f"check entry not found: {check_type}")
