from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as XmlET
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatch
from math import ceil
from pathlib import Path
from typing import DefaultDict, Dict, Iterable, List, Mapping, MutableMapping, Optional, Protocol, Sequence


MODULE_ANALYSIS_SCHEMA_VERSION = "aov-module-analysis/v1"


@dataclass(frozen=True)
class ModuleContext:
	tdr_root: str = ""
	region_code: str = "TW"

	def dtxml_path(self, file_name: str) -> Path:
		return Path(self.tdr_root) / "Xml" / "Garena" / self.region_code.upper() / "CommonCore" / file_name


class ChangeSetModule(Protocol):
	id: str
	name: str

	def matches(self, change: Mapping[str, object]) -> bool:
		...

	def analyze(self, changes: Sequence[Mapping[str, object]], context: ModuleContext) -> Dict[str, object]:
		...


def _row(change: Mapping[str, object]) -> Dict[str, str]:
	value = change.get("after")
	if not isinstance(value, Mapping):
		value = change.get("values")
	if not isinstance(value, Mapping):
		value = change.get("before")
	if not isinstance(value, Mapping):
		return {}
	return {str(key): str(item) for key, item in value.items()}


def _business_key(change: Mapping[str, object]) -> str:
	value = change.get("business_key")
	if isinstance(value, Mapping):
		return str(value.get("display", ""))
	return str(value or "")


def _business_key_value(change: Mapping[str, object], column: str) -> str:
	value = change.get("business_key")
	if isinstance(value, Mapping):
		columns = [str(item) for item in value.get("columns", [])]
		values = [str(item) for item in value.get("values", [])]
		if column in columns and columns.index(column) < len(values):
			return values[columns.index(column)]
	for part in _business_key(change).split(","):
		name, separator, item = part.strip().partition("=")
		if separator and name.strip() == column:
			return item.strip()
	return ""


def _change_reference(change: Mapping[str, object]) -> Dict[str, object]:
	reference = {
		"file_name": str(change.get("file_name", "")),
		"sheet": str(change.get("sheet", "")),
		"business_key": _business_key(change),
		"change_type": str(change.get("change_type", "")),
		"revisions": list(change.get("revisions", [])),
	}
	if change.get("change_type") == "modified":
		reference["changed_fields"] = list(change.get("changed_fields", []))
	return reference


def _field_change_details(change: Mapping[str, object]) -> List[Dict[str, str]]:
	before = change.get("before") if isinstance(change.get("before"), Mapping) else {}
	after = change.get("after") if isinstance(change.get("after"), Mapping) else {}
	return [
		{
			"field": str(field),
			"before": str(before.get(str(field), "")),
			"after": str(after.get(str(field), "")),
		}
		for field in change.get("changed_fields", [])
	]


def _read_sheet(context: ModuleContext, file_name: str, sheet_name: str) -> List[Dict[str, str]]:
	if not context.tdr_root:
		return []
	path = context.dtxml_path(file_name)
	if not path.is_file():
		return []
	root = XmlET.parse(path).getroot()
	for sheet in root.findall("Sheet"):
		if sheet.get("Name") != sheet_name:
			continue
		return [
			{
				str(cell.get("Name")): "".join(cell.itertext()).strip()
				for cell in row.findall("Cell")
				if cell.get("Name")
			}
			for row in sheet.findall("Row")
		]
	return []


def _read_all_sheets(context: ModuleContext, file_name: str) -> Dict[str, List[Dict[str, str]]]:
	if not context.tdr_root:
		return {}
	path = context.dtxml_path(file_name)
	return _read_all_sheets_path(path)


def _read_all_sheets_path(path: Path) -> Dict[str, List[Dict[str, str]]]:
	if not path.is_file():
		return {}
	result: Dict[str, List[Dict[str, str]]] = {}
	root = XmlET.parse(path).getroot()
	for sheet in root.findall("Sheet"):
		sheet_name = str(sheet.get("Name") or "")
		if not sheet_name:
			continue
		result[sheet_name] = [
			{
				str(cell.get("Name")): "".join(cell.itertext()).strip()
				for cell in row.findall("Cell")
				if cell.get("Name")
			}
			for row in sheet.findall("Row")
		]
	return result


RANDOM_REWARD_FILE = "35.svr下发随机奖励配置表.dtxml"
RANDOM_REWARD_FALLBACK_FILE = "【运营配置】35.物品掉落配置表.dtxml"
RANDOM_REWARD_SHEETS = {"随机奖励配置表"}
CONDITION_ACTIVITY_SHEET = "条件活动表"
EXCHANGE_ACTIVITY_SHEET = "兑换活动表"
COLLECT_EXCHANGE_ACTIVITY_SHEET = "收集兑换活动表"
ACTIVE_POINT_ACTIVITY_SHEET = "活跃度活动表"
SIGN_IN_ACTIVITY_SHEET = "签到活动表"
TEXT_ACTIVITY_SHEET = "文本活动表"
CONDITION_REWARD_FIELD = re.compile(r"^条件(?P<index>\d+)(?P<timed>限时)?奖励ID$")
SIGN_IN_REWARD_FIELD = re.compile(r"^天数(?P<index>\d+)奖励ID$")

REWARD_ENTITY_SPECS = {
	"随机英雄": [
		("【运营配置】11.英雄信息表*.dtxml", "英雄信息", "武将ID", ("武将名", "英雄名称")),
	],
	"随机皮肤": [
		("【运营配置】73.皮肤配置表*.dtxml", "皮肤配置表", "ID", ("皮肤名称",)),
		("73.svr下发皮肤配置表*.dtxml", "皮肤配置表", "ID", ("皮肤名称",)),
	],
	"随机头像框": [
		("【运营配置】头像框信息表*.dtxml", "头像框信息表", "头像框ID", ("头像框名称", "头像框描述")),
	],
	"随机头像": [
		("【运营配置】玩家头像信息表*.dtxml", "玩家头像信息", "头像ID", ("头像名称", "头像描述")),
		("玩家头像信息表svr下发*.dtxml", "玩家头像信息", "头像ID", ("头像名称", "头像描述")),
	],
	"随机局内动作": [
		("【运营配置】142.局内动作配置表*.dtxml", "局内动作上下架表", "ID", ("名称", "部件描述")),
		("142.局内动作上下架与促销表*.dtxml", "局内动作上下架表", "局内动作ID", ("名称", "动作描述")),
		("142.局内动作上下架与促销表*.dtxml", "svr局内动作上下架表", "局内动作ID", ("名称", "动作描述")),
	],
	"随机皮肤部件": [
		("皮肤部件上下架与促销表*.dtxml", "皮肤部件上下架表", "皮肤部件ID", ("名称", "描述")),
		("皮肤部件上下架与促销表*.dtxml", "svr皮肤部件上下架表", "皮肤部件ID", ("名称", "描述")),
	],
	"随机战场播报": [
		("420.播报上下架与促销表*.dtxml", "播报上下架表", "播报ID", ("播报名称", "播报描述")),
		("420.播报上下架与促销表*.dtxml", "svr播报上下架表", "播报ID", ("播报名称", "播报描述")),
	],
	"随机个性按键": [
		("928.个性按键上下架与促销表*.dtxml", "个性按键上下架表", "个性按键ID", ("按键名称", "按键描述")),
		("928.个性按键上下架与促销表*.dtxml", "svr个性按键上下架表", "个性按键ID", ("按键名称", "按键描述")),
	],
	"随机局内特效": [
		("89.局内特效上下架与促销表*.dtxml", "局内特效上下架表", "局内特效ID", ("特效名称", "特效描述")),
		("89.局内特效上下架与促销表*.dtxml", "svr局内特效上下架表", "局内特效ID", ("特效名称", "特效描述")),
		("【运营配置】88.局内特效配置表*.dtxml", "局内特效配置表", "特效ID", ("特效名称", "特效描述")),
	],
	"随机称号": [
		("【运营配置】生涯称号配置表*.dtxml", "生涯称号配置表", "称号ID", ("称号名称", "称号文案")),
	],
	"随机个性戳戳": [
		("930.个性戳戳信息表*.dtxml", "个性戳戳配置", "ID", ("名称", "描述")),
	],
	"随机小兵皮肤": [
		("【运营配置】933.小兵皮肤上下架与促销表*.dtxml", "小兵皮肤上下架表", "小兵皮肤ID", ("名称", "描述")),
	],
	"随机灵宝部件": [
		("【运营配置】灵宝上下架与促销表*.dtxml", "灵宝部件上下架表", "灵宝部件ID", ("名称", "描述")),
		("【运营配置】灵宝上下架与促销表*.dtxml", "svr灵宝部件上下架表", "灵宝部件ID", ("名称", "描述")),
	],
	"随机灵宝套装": [
		("【运营配置】灵宝上下架与促销表*.dtxml", "灵宝部件上下架表", "灵宝部件ID", ("名称", "描述")),
		("【运营配置】灵宝上下架与促销表*.dtxml", "svr灵宝部件上下架表", "灵宝部件ID", ("名称", "描述")),
	],
}

REWARD_VALUE_TYPES = {
	"随机钻石", "随机符文碎片", "随机金币", "随机TOKEN",
	"随机VALORPASS积分", "随机点券", "随机星币",
}

TEXT_LINKED_ACTIVITY_SHEETS = {
	"条件活动": CONDITION_ACTIVITY_SHEET,
	"新版月度签到活动": "月度签到活动表",
	"ilua热更活动": "ilua热更活动",
}

ACTIVITY_TYPE_LABELS = {
	"新手专属签到表": "新手签到活动",
	"月度签到活动表": "月度签到活动",
	"定时活动表": "定时活动",
	SIGN_IN_ACTIVITY_SHEET: "签到活动",
	EXCHANGE_ACTIVITY_SHEET: "兑换活动",
	CONDITION_ACTIVITY_SHEET: "条件活动",
	TEXT_ACTIVITY_SHEET: "文本活动",
	ACTIVE_POINT_ACTIVITY_SHEET: "活跃度活动",
	COLLECT_EXCHANGE_ACTIVITY_SHEET: "收集兑换活动",
	"翻倍活动表": "翻倍活动",
	"回流拍脸活动表": "回流活动",
	"兑换码活动表": "兑换码活动",
	"特推商品表": "商城活动",
	"ilua聚合配置表": "ilua活动",
}


def _reward_entity_changes(change: Mapping[str, object]) -> List[tuple[str, str]]:
	file_name = str(change.get("file_name", ""))
	sheet_name = str(change.get("sheet", ""))
	entities = []
	if (
		(fnmatch(file_name, "【运营配置】41.道具信息表*.dtxml") or fnmatch(file_name, "41.svr下发道具信息表*.dtxml"))
		and sheet_name in {"道具信息", "道具信息增量"}
	):
		entities.extend(("随机道具", entity_id) for entity_id in _changed_values(change, "ID"))
	for reward_type, specs in REWARD_ENTITY_SPECS.items():
		for pattern, expected_sheet, id_field, _ in specs:
			if fnmatch(file_name, pattern) and sheet_name == expected_sheet:
				entities.extend((reward_type, entity_id) for entity_id in _changed_values(change, id_field))
	return list(dict.fromkeys(entities))


def _changed_values(change: Mapping[str, object], field: str) -> List[str]:
	values = []
	for side in ("before", "after"):
		row = change.get(side)
		if isinstance(row, Mapping) and str(row.get(field, "")).strip():
			values.append(str(row[field]).strip())
	value = _business_key_value(change, field)
	if value:
		values.append(value)
	return list(dict.fromkeys(values))


def _reward_components(row: Mapping[str, str]) -> List[Dict[str, object]]:
	components = []
	for position in range(1, 33):
		index = str(position)
		item_id = row.get(f"奖励{index}ID", "")
		reward_type = row.get(f"奖励{index}类型", "")
		quantity_min = row.get(f"奖励{index}数量下限", "")
		quantity_max = row.get(f"奖励{index}数量上限", "")
		probability = row.get(f"奖励{index}概率万分比", "")
		if not any((item_id, reward_type, quantity_min, quantity_max, probability)):
			continue
		components.append({
			"index": index,
			"type": reward_type,
			"is_item": "道具" in reward_type,
			"item_id": item_id,
			"quantity_min": quantity_min,
			"quantity_max": quantity_max,
			"probability": probability,
		})
	return components


def _reward_quantity_label(reward: Mapping[str, object]) -> str:
	minimum = str(reward.get("quantity_min", ""))
	maximum = str(reward.get("quantity_max", ""))
	if minimum and maximum and minimum != maximum:
		return f"{minimum}-{maximum}"
	return minimum or maximum


def _multiply_reward_quantity(outer: object, inner: object) -> str:
	outer_value = str(outer or "")
	inner_value = str(inner or "")
	if not outer_value:
		return inner_value
	if not inner_value:
		return outer_value
	try:
		return str(int(outer_value) * int(inner_value))
	except ValueError:
		return inner_value


def _reward_leaf_labels(reward: Mapping[str, object]) -> List[str]:
	labels = []
	for leaf in reward.get("leaf_rewards", []):
		if not isinstance(leaf, Mapping):
			continue
		name = str(leaf.get("entity_name", ""))
		entity_id = str(leaf.get("entity_id", ""))
		entity_type = str(leaf.get("entity_type", "奖励"))
		identity = " ".join(value for value in (entity_id, name) if value)
		label = f"{entity_type} {identity}".strip()
		quantity = _reward_quantity_label(leaf)
		if quantity:
			label += f" ×{quantity}"
		if not leaf.get("resolved", False):
			label += "（未找到定义）"
		labels.append(label)
	return labels


class ItemDefinitionCatalog:
	"""Resolve item definitions across client and server tables using one priority policy."""

	SOURCE_SPECS = (
		("【运营配置】41.道具信息表*.dtxml", "道具信息", "client_main", 10),
		("【运营配置】41.道具信息表*.dtxml", "道具信息增量", "client_increment", 20),
		("41.svr下发道具信息表*.dtxml", "道具信息", "server", 30),
	)

	def __init__(self, context: ModuleContext) -> None:
		self.definitions: DefaultDict[str, List[Dict[str, object]]] = defaultdict(list)
		self.rows: Dict[str, Dict[str, str]] = {}
		self.sources: Dict[str, str] = {}
		self.source_sheets: Dict[str, str] = {}
		if not context.tdr_root:
			return
		common_core = context.dtxml_path("placeholder.dtxml").parent
		for pattern, sheet_name, source_kind, priority in self.SOURCE_SPECS:
			for path in sorted(common_core.glob(pattern)):
				for row in _read_sheet(context, path.name, sheet_name):
					item_id = row.get("ID", "")
					if not item_id:
						continue
					self.definitions[item_id].append({
						"source_kind": source_kind,
						"priority": priority,
						"file_name": path.name,
						"sheet": sheet_name,
						"category": row.get("类型", ""),
						"name": row.get("名称", ""),
						"row": row,
					})
		for item_id, definitions in self.definitions.items():
			selected = max(definitions, key=lambda item: int(item["priority"]))
			self.rows[item_id] = dict(selected["row"])
			self.sources[item_id] = str(selected["file_name"])
			self.source_sheets[item_id] = str(selected["sheet"])

	def resolution(self, item_id: str) -> Dict[str, object]:
		definitions = self.definitions.get(item_id, [])
		if not definitions:
			return {
				"selected_source_kind": "changeset_fallback",
				"selected_file_name": "",
				"selected_sheet": "",
				"available_sources": [],
				"category_conflict": False,
				"categories": [],
			}
		selected = max(definitions, key=lambda item: int(item["priority"]))
		categories = list(dict.fromkeys(
			str(item.get("category", "")) for item in definitions if item.get("category")
		))
		return {
			"selected_source_kind": selected["source_kind"],
			"selected_file_name": selected["file_name"],
			"selected_sheet": selected["sheet"],
			"available_sources": [
				{
					"source_kind": item["source_kind"],
					"file_name": item["file_name"],
					"sheet": item["sheet"],
					"category": item["category"],
					"name": item["name"],
					"selected": item is selected,
				}
				for item in definitions
			],
			"category_conflict": len(categories) > 1,
			"categories": categories,
		}


class ActivityReferenceIndex:
	"""Build direct condition-activity impact paths from the current dtxml snapshot."""

	def __init__(self, context: ModuleContext) -> None:
		self.context = context
		self._entity_catalogs: Dict[str, Dict[str, Dict[str, str]]] = {}
		self.daily_sheets = _read_all_sheets(context, "日常活动表.dtxml")
		self.reward_rows: Dict[str, Dict[str, str]] = {}
		self.reward_sources: Dict[str, str] = {}
		for file_name in (RANDOM_REWARD_FALLBACK_FILE, RANDOM_REWARD_FILE):
			for sheet_name, rows in _read_all_sheets(context, file_name).items():
				if sheet_name not in RANDOM_REWARD_SHEETS:
					continue
				for row in rows:
					reward_id = row.get("随机奖励ID", "")
					if reward_id:
						self.reward_rows[reward_id] = row
						self.reward_sources[reward_id] = file_name
		self.item_catalog = ItemDefinitionCatalog(context)
		self.item_rows = self.item_catalog.rows
		self.item_sources = self.item_catalog.sources

		self.reward_to_activities: DefaultDict[str, List[Dict[str, object]]] = defaultdict(list)
		for row in self.daily_sheets.get(CONDITION_ACTIVITY_SHEET, []):
			activity_id = row.get("活动ID", "")
			if not activity_id:
				continue
			for field, reward_id in row.items():
				match = CONDITION_REWARD_FIELD.match(field)
				if not match or not reward_id or reward_id in {"0", "0x0"}:
					continue
				self.reward_to_activities[reward_id].append({
					"activity_id": activity_id,
					"activity_name": row.get("活动名称") or row.get("活动标题", ""),
					"sheet": CONDITION_ACTIVITY_SHEET,
					"field": field,
					"condition_index": match.group("index"),
					"timed_reward": bool(match.group("timed")),
					"row": row,
				})
		for row in self.daily_sheets.get(ACTIVE_POINT_ACTIVITY_SHEET, []):
			activity_id = row.get("活动ID", "")
			if not activity_id:
				continue
			for tier_index in range(1, 6):
				reward_id = row.get(f"第{tier_index}档奖励", "")
				if not reward_id or reward_id in {"0", "0x0"}:
					continue
				self.reward_to_activities[reward_id].append({
					"activity_id": activity_id,
					"activity_name": row.get("活动名称") or row.get("活动标题", ""),
					"sheet": ACTIVE_POINT_ACTIVITY_SHEET,
					"field": f"第{tier_index}档奖励",
					"tier_index": str(tier_index),
					"row": row,
				})
		for row in self.daily_sheets.get(SIGN_IN_ACTIVITY_SHEET, []):
			activity_id = row.get("活动ID", "")
			if not activity_id:
				continue
			for field, reward_id in row.items():
				match = SIGN_IN_REWARD_FIELD.match(field)
				if not match or not reward_id or reward_id in {"0", "0x0"}:
					continue
				self.reward_to_activities[reward_id].append({
					"activity_id": activity_id,
					"activity_name": row.get("活动名称") or row.get("活动标题", ""),
					"sheet": SIGN_IN_ACTIVITY_SHEET,
					"field": field,
					"day_index": match.group("index"),
					"row": row,
				})

		self.item_to_rewards: DefaultDict[str, List[str]] = defaultdict(list)
		self.entity_to_rewards: DefaultDict[tuple[str, str], List[str]] = defaultdict(list)
		for reward_id in self.reward_rows:
			for item_id in self._reward_item_ids(reward_id):
				self.item_to_rewards[item_id].append(reward_id)
			for reward_type, entity_id in self._reward_entities(reward_id):
				self.entity_to_rewards[(reward_type, entity_id)].append(reward_id)

		self.item_to_exchange_activities: DefaultDict[str, List[Dict[str, object]]] = defaultdict(list)
		for row in self.daily_sheets.get(EXCHANGE_ACTIVITY_SHEET, []):
			activity_id = row.get("活动ID", "")
			if not activity_id:
				continue
			references = [(
				"output",
				"兑换产出物品ID",
				row.get("兑换产出物品类型", ""),
				row.get("兑换产出物品ID", ""),
			)]
			for index in range(1, 6):
				references.append((
					"cost",
					f"兑换收集物品{index}ID",
					row.get(f"兑换收集物品{index}类型", ""),
					row.get(f"兑换收集物品{index}ID", ""),
				))
			for role, field, object_type, object_id in references:
				if "道具" not in object_type or not object_id or object_id in {"0", "0x0"}:
					continue
				self.item_to_exchange_activities[object_id].append({
					"activity_id": activity_id,
					"activity_name": row.get("活动名称") or row.get("活动标题", ""),
					"sheet": EXCHANGE_ACTIVITY_SHEET,
					"field": field,
					"exchange_index": row.get("活动索引", ""),
					"exchange_role": role,
					"row": row,
				})

		self.child_activity_to_collect: DefaultDict[tuple[str, str], List[Dict[str, object]]] = defaultdict(list)
		for row in self.daily_sheets.get(COLLECT_EXCHANGE_ACTIVITY_SHEET, []):
			parent_id = row.get("活动ID", "")
			if not parent_id:
				continue
			for child_sheet, field, role in (
				(CONDITION_ACTIVITY_SHEET, "条件活动ID", "acquisition"),
				(EXCHANGE_ACTIVITY_SHEET, "兑换活动ID", "exchange"),
			):
				child_id = row.get(field, "")
				if not child_id or child_id in {"0", "0x0"}:
					continue
				self.child_activity_to_collect[(child_sheet, child_id)].append({
					"activity_id": parent_id,
					"activity_name": row.get("活动名称") or row.get("活动标题", ""),
					"sheet": COLLECT_EXCHANGE_ACTIVITY_SHEET,
					"field": field,
					"collect_role": role,
					"child_sheet": child_sheet,
					"child_activity_id": child_id,
					"row": row,
				})

		self.child_activity_to_active: DefaultDict[tuple[str, str], List[Dict[str, object]]] = defaultdict(list)
		for row in self.daily_sheets.get(ACTIVE_POINT_ACTIVITY_SHEET, []):
			parent_id = row.get("活动ID", "")
			child_id = row.get("关联的条件活动ID", "")
			if not parent_id or not child_id or child_id in {"0", "0x0"}:
				continue
			self.child_activity_to_active[(CONDITION_ACTIVITY_SHEET, child_id)].append({
				"activity_id": parent_id,
				"activity_name": row.get("活动名称") or row.get("活动标题", ""),
				"sheet": ACTIVE_POINT_ACTIVITY_SHEET,
				"field": "关联的条件活动ID",
				"child_sheet": CONDITION_ACTIVITY_SHEET,
				"child_activity_id": child_id,
				"row": row,
			})

		self.child_activity_to_text: DefaultDict[tuple[str, str], List[Dict[str, object]]] = defaultdict(list)
		for row in self.daily_sheets.get(TEXT_ACTIVITY_SHEET, []):
			parent_id = row.get("活动ID", "")
			child_id = row.get("关联的活动ID", "")
			linked_type = row.get("关联的活动类型", "")
			child_sheet = TEXT_LINKED_ACTIVITY_SHEETS.get(linked_type, linked_type)
			if not parent_id or not child_id or child_id in {"0", "0x0"} or not child_sheet:
				continue
			self.child_activity_to_text[(child_sheet, child_id)].append({
				"activity_id": parent_id,
				"activity_name": row.get("活动名称") or row.get("活动标题", ""),
				"sheet": TEXT_ACTIVITY_SHEET,
				"field": "关联的活动ID",
				"child_sheet": child_sheet,
				"child_activity_id": child_id,
				"linked_activity_type": linked_type,
				"row": row,
			})

		self.item_to_progress_conditions: DefaultDict[str, List[Dict[str, str]]] = defaultdict(list)
		for row in _read_sheet(context, "159.通用条件配置表.dtxml", "通用条件配置表"):
			if "拥有指定物品达到指定数量" not in row.get("条件类型", ""):
				continue
			item_id = row.get("参数2", "")
			if item_id:
				self.item_to_progress_conditions[item_id].append(row)

		self.common_condition_to_progress_activities: DefaultDict[str, List[Dict[str, object]]] = defaultdict(list)
		for row in self.daily_sheets.get(CONDITION_ACTIVITY_SHEET, []):
			activity_id = row.get("活动ID", "")
			if not activity_id:
				continue
			for index in range(1, 33):
				if row.get(f"条件{index}类型") != "活动_通用条件":
					continue
				condition_id = row.get(f"条件{index}参数1", "")
				if not condition_id:
					continue
				self.common_condition_to_progress_activities[condition_id].append({
					"activity_id": activity_id,
					"activity_name": row.get("活动名称") or row.get("活动标题", ""),
					"sheet": CONDITION_ACTIVITY_SHEET,
					"condition_index": str(index),
					"condition_id": condition_id,
					"condition_description": row.get(f"条件{index}简介", ""),
					"target_value": row.get(f"条件{index}目标值", ""),
					"reward_id": row.get(f"条件{index}奖励ID", ""),
					"daily_reset": row.get(f"条件{index}是否每日刷新", ""),
					"row": row,
				})

		self.item_to_ilua_progress: DefaultDict[str, List[Dict[str, object]]] = defaultdict(list)
		for sheet_name, rows in _read_all_sheets(context, "157.ilua热更活动聚合配置表.dtxml").items():
			for row in rows:
				raw_json = row.get("活动详情的json串", "")
				if not raw_json:
					continue
				try:
					config = json.loads(raw_json)
				except (TypeError, ValueError):
					continue
				if not isinstance(config, Mapping) or not config.get("tokenID"):
					continue
				item_id = str(config["tokenID"])
				self.item_to_ilua_progress[item_id].append({
					"activity_id": row.get("活动ID", ""),
					"activity_name": row.get("活动名称") or row.get("活动标题", ""),
					"sheet": sheet_name,
					"config_type": str(config.get("configType", "")),
					"progress_activity_id": str(config.get("leiJiActID", "")),
					"rule_id": str(config.get("ruleID", "")),
					"calendar_activity_id": str(config.get("calendarID", "")),
					"start_time": _format_compact_time(row.get("开始时间", "")),
					"end_time": _format_compact_time(row.get("结束时间", "")),
				})

	def token_progress(self, item_id: str) -> Dict[str, object]:
		conditions = []
		progress_activities: Dict[tuple[str, str], Dict[str, object]] = {}
		for condition_row in self.item_to_progress_conditions.get(item_id, []):
			condition_id = condition_row.get("条件id", "")
			conditions.append({
				"condition_id": condition_id,
				"condition_description": condition_row.get("条件简介", ""),
				"condition_type": condition_row.get("条件类型", ""),
				"item_type_parameter": condition_row.get("参数1", ""),
				"item_id": condition_row.get("参数2", ""),
			})
			for reference in self.common_condition_to_progress_activities.get(condition_id, []):
				key = (str(reference["sheet"]), str(reference["activity_id"]))
				activity = progress_activities.setdefault(key, {
					"activity_id": reference["activity_id"],
					"activity_name": reference["activity_name"],
					"activity_type": ACTIVITY_TYPE_LABELS.get(str(reference["sheet"]), str(reference["sheet"])),
					"sheet": reference["sheet"],
					"start_time_raw": reference["row"].get("开始时间", ""),
					"end_time_raw": reference["row"].get("结束时间", ""),
					"start_time": _format_compact_time(reference["row"].get("开始时间", "")),
					"end_time": _format_compact_time(reference["row"].get("结束时间", "")),
					"stages": [],
				})
				reward_id = str(reference.get("reward_id", ""))
				activity["stages"].append({
					"index": reference["condition_index"],
					"condition_id": condition_id,
					"description": reference["condition_description"],
					"target_value": reference["target_value"],
					"reward_id": reward_id,
					"reward": self.reward(reward_id) if reward_id else {},
					"daily_reset": reference["daily_reset"],
				})
		return {
			"conditions": conditions,
			"activities": list(progress_activities.values()),
			"ilua_activities": list(self.item_to_ilua_progress.get(item_id, [])),
		}

	def impacts_for_changes(self, changes: Sequence[Mapping[str, object]]) -> Dict[str, List[Dict[str, object]]]:
		impacts: DefaultDict[str, List[Dict[str, object]]] = defaultdict(list)
		for change in changes:
			file_name = str(change.get("file_name", ""))
			sheet_name = str(change.get("sheet", ""))
			if file_name == "日常活动表.dtxml":
				child_id = _row(change).get("活动ID") or _business_key_value(change, "活动ID")
				for reference in self.child_activity_to_text.get((sheet_name, child_id), []):
					impact = {
						"trigger_type": "activity",
						"trigger_id": child_id,
						"via_reward_id": "",
						"via_activity_id": child_id,
						"activity_id": reference["activity_id"],
						"activity_name": reference["activity_name"],
						"sheet": reference["sheet"],
						"field": reference["field"],
						"child_sheet": reference["child_sheet"],
						"linked_activity_type": reference["linked_activity_type"],
						"source_change": _change_reference(change),
						"row": reference["row"],
					}
					if impact not in impacts[str(reference["activity_id"])]:
						impacts[str(reference["activity_id"])].append(impact)
			if file_name == "日常活动表.dtxml" and sheet_name in {CONDITION_ACTIVITY_SHEET, EXCHANGE_ACTIVITY_SHEET}:
				child_id = _row(change).get("活动ID") or _business_key_value(change, "活动ID")
				for reference in self.child_activity_to_collect.get((sheet_name, child_id), []):
					impact = {
						"trigger_type": "activity",
						"trigger_id": child_id,
						"via_reward_id": "",
						"via_activity_id": child_id,
						"activity_id": reference["activity_id"],
						"activity_name": reference["activity_name"],
						"sheet": reference["sheet"],
						"field": reference["field"],
						"collect_role": reference["collect_role"],
						"child_sheet": reference["child_sheet"],
						"source_change": _change_reference(change),
						"row": reference["row"],
					}
					if impact not in impacts[str(reference["activity_id"])]:
						impacts[str(reference["activity_id"])].append(impact)
				for reference in self.child_activity_to_active.get((sheet_name, child_id), []):
					impact = {
						"trigger_type": "activity",
						"trigger_id": child_id,
						"via_reward_id": "",
						"via_activity_id": child_id,
						"activity_id": reference["activity_id"],
						"activity_name": reference["activity_name"],
						"sheet": reference["sheet"],
						"field": reference["field"],
						"child_sheet": reference["child_sheet"],
						"source_change": _change_reference(change),
						"row": reference["row"],
					}
					if impact not in impacts[str(reference["activity_id"])]:
						impacts[str(reference["activity_id"])].append(impact)
			reward_ids: List[tuple[str, str, str]] = []
			if file_name in {RANDOM_REWARD_FILE, RANDOM_REWARD_FALLBACK_FILE} and sheet_name in RANDOM_REWARD_SHEETS:
				reward_ids.extend((reward_id, "reward", reward_id) for reward_id in _changed_values(change, "随机奖励ID"))
			else:
				for reward_type, entity_id in _reward_entity_changes(change):
					trigger_type = "item" if reward_type == "随机道具" else "entity"
					reward_ids.extend(
						(reward_id, trigger_type, entity_id)
						for reward_id in self.entity_to_rewards.get((reward_type, entity_id), [])
					)
					if reward_type != "随机道具":
						continue
					item_id = entity_id
					for reference in self.item_to_exchange_activities.get(item_id, []):
						impact = {
							"trigger_type": "item",
							"trigger_id": item_id,
							"trigger_entity_type": "道具",
							"via_reward_id": "",
							"activity_id": reference["activity_id"],
							"activity_name": reference["activity_name"],
							"sheet": reference["sheet"],
							"field": reference["field"],
							"exchange_index": reference["exchange_index"],
							"exchange_role": reference["exchange_role"],
							"source_change": _change_reference(change),
							"row": reference["row"],
						}
						if impact not in impacts[str(reference["activity_id"])]:
							impacts[str(reference["activity_id"])].append(impact)

			for reward_id, trigger_type, trigger_id in reward_ids:
				for reference in self.reward_to_activities.get(reward_id, []):
					impact = {
						"trigger_type": trigger_type,
						"trigger_id": trigger_id,
						"via_reward_id": reward_id,
						"activity_id": reference["activity_id"],
						"activity_name": reference["activity_name"],
						"sheet": reference["sheet"],
						"field": reference["field"],
						"condition_index": reference.get("condition_index", ""),
						"timed_reward": reference.get("timed_reward", False),
						"tier_index": reference.get("tier_index", ""),
						"day_index": reference.get("day_index", ""),
						"trigger_entity_type": next((
							reward_type.removeprefix("随机")
							for reward_type, entity_id in _reward_entity_changes(change)
							if entity_id == trigger_id
						), ""),
						"source_change": _change_reference(change),
						"row": reference["row"],
					}
					if impact not in impacts[str(reference["activity_id"])]:
						impacts[str(reference["activity_id"])].append(impact)

		child_impacts = [
			impact
			for activity_impacts in impacts.values()
			for impact in activity_impacts
			if impact.get("sheet") in {CONDITION_ACTIVITY_SHEET, EXCHANGE_ACTIVITY_SHEET}
		]
		for child_impact in child_impacts:
			child_key = (str(child_impact["sheet"]), str(child_impact["activity_id"]))
			for reference in self.child_activity_to_collect.get(child_key, []):
				impact = {
					"trigger_type": child_impact.get("trigger_type", "activity"),
					"trigger_id": child_impact.get("trigger_id", child_impact["activity_id"]),
					"via_reward_id": child_impact.get("via_reward_id", ""),
					"via_activity_id": child_impact["activity_id"],
					"activity_id": reference["activity_id"],
					"activity_name": reference["activity_name"],
					"sheet": reference["sheet"],
					"field": reference["field"],
					"collect_role": reference["collect_role"],
					"child_sheet": reference["child_sheet"],
					"condition_index": child_impact.get("condition_index", ""),
					"exchange_index": child_impact.get("exchange_index", ""),
					"source_change": child_impact["source_change"],
					"row": reference["row"],
				}
				if impact not in impacts[str(reference["activity_id"])]:
					impacts[str(reference["activity_id"])].append(impact)
			for reference in self.child_activity_to_active.get(child_key, []):
				impact = {
					"trigger_type": child_impact.get("trigger_type", "activity"),
					"trigger_id": child_impact.get("trigger_id", child_impact["activity_id"]),
					"via_reward_id": child_impact.get("via_reward_id", ""),
					"via_activity_id": child_impact["activity_id"],
					"activity_id": reference["activity_id"],
					"activity_name": reference["activity_name"],
					"sheet": reference["sheet"],
					"field": reference["field"],
					"child_sheet": reference["child_sheet"],
					"condition_index": child_impact.get("condition_index", ""),
					"source_change": child_impact["source_change"],
					"row": reference["row"],
				}
				if impact not in impacts[str(reference["activity_id"])]:
					impacts[str(reference["activity_id"])].append(impact)

		text_child_impacts = [
			impact
			for activity_impacts in list(impacts.values())
			for impact in activity_impacts
			if impact.get("sheet") != TEXT_ACTIVITY_SHEET
		]
		for child_impact in text_child_impacts:
			child_key = (str(child_impact["sheet"]), str(child_impact["activity_id"]))
			for reference in self.child_activity_to_text.get(child_key, []):
				impact = {
					"trigger_type": child_impact.get("trigger_type", "activity"),
					"trigger_id": child_impact.get("trigger_id", child_impact["activity_id"]),
					"trigger_entity_type": child_impact.get("trigger_entity_type", ""),
					"via_reward_id": child_impact.get("via_reward_id", ""),
					"via_activity_id": child_impact["activity_id"],
					"activity_id": reference["activity_id"],
					"activity_name": reference["activity_name"],
					"sheet": reference["sheet"],
					"field": reference["field"],
					"child_sheet": reference["child_sheet"],
					"linked_activity_type": reference["linked_activity_type"],
					"condition_index": child_impact.get("condition_index", ""),
					"day_index": child_impact.get("day_index", ""),
					"source_change": child_impact["source_change"],
					"row": reference["row"],
				}
				if impact not in impacts[str(reference["activity_id"])]:
					impacts[str(reference["activity_id"])].append(impact)
		return dict(impacts)

	def _reward_item_ids(self, reward_id: str, trail: tuple[str, ...] = ()) -> List[str]:
		if reward_id in trail:
			return []
		item_ids = []
		for component in _reward_components(self.reward_rows.get(reward_id, {})):
			if component["is_item"] and component["item_id"]:
				item_ids.append(str(component["item_id"]))
			elif component["type"] == "随机嵌套" and component["item_id"]:
				item_ids.extend(self._reward_item_ids(str(component["item_id"]), (*trail, reward_id)))
		return list(dict.fromkeys(item_ids))

	def _reward_entities(self, reward_id: str, trail: tuple[str, ...] = ()) -> List[tuple[str, str]]:
		if reward_id in trail:
			return []
		entities = []
		for component in _reward_components(self.reward_rows.get(reward_id, {})):
			reward_type = str(component["type"])
			entity_id = str(component["item_id"])
			if reward_type == "随机嵌套" and entity_id:
				entities.extend(self._reward_entities(entity_id, (*trail, reward_id)))
			elif entity_id and reward_type not in REWARD_VALUE_TYPES:
				entities.append((reward_type, entity_id))
		return list(dict.fromkeys(entities))

	def _entity_catalog(self, reward_type: str) -> Dict[str, Dict[str, str]]:
		if reward_type in self._entity_catalogs:
			return self._entity_catalogs[reward_type]
		catalog: Dict[str, Dict[str, str]] = {}
		if self.context.tdr_root:
			common_core = self.context.dtxml_path("placeholder.dtxml").parent
			for pattern, sheet_name, id_field, name_fields in REWARD_ENTITY_SPECS.get(reward_type, []):
				for path in sorted(common_core.glob(pattern)):
					for row in _read_sheet(self.context, path.name, sheet_name):
						entity_id = row.get(id_field, "")
						if not entity_id:
							continue
						name = next((row.get(field, "") for field in name_fields if row.get(field)), "")
						catalog[entity_id] = {
							"name": name,
							"source_file": path.name,
							"sheet": sheet_name,
						}
		self._entity_catalogs[reward_type] = catalog
		return catalog

	def reward(self, reward_id: str, trail: tuple[str, ...] = ()) -> Dict[str, object]:
		if reward_id in trail:
			return {
				"reward_id": reward_id,
				"description": "",
				"components": [],
				"leaf_rewards": [{
					"entity_type": "嵌套奖励",
					"entity_id": reward_id,
					"entity_name": "循环引用",
					"resolved": False,
					"resolution_error": "nested_reward_cycle",
				}],
				"resolved": False,
				"source_file": self.reward_sources.get(reward_id, ""),
			}
		row = self.reward_rows.get(reward_id, {})
		components = []
		for component in _reward_components(row):
			reward_type = str(component["type"])
			entity_id = str(component["item_id"])
			resolved_component = dict(component)
			leaves = []
			if reward_type == "随机嵌套":
				nested = self.reward(entity_id, (*trail, reward_id)) if entity_id else None
				resolved_component["nested_reward"] = nested
				if nested is not None:
					leaves = [
						{
							**leaf,
							"quantity_min": _multiply_reward_quantity(
								component.get("quantity_min"), leaf.get("quantity_min")
							),
							"quantity_max": _multiply_reward_quantity(
								component.get("quantity_max"), leaf.get("quantity_max")
							),
							"quantity_path": [
								{
									"reward_id": reward_id,
									"minimum": component.get("quantity_min", ""),
									"maximum": component.get("quantity_max", ""),
								},
								*leaf.get("quantity_path", []),
							],
							"reward_path": [reward_id, *leaf.get("reward_path", [entity_id])],
						}
						for leaf in nested.get("leaf_rewards", [])
					]
			elif component["is_item"]:
				item = self.item_rows.get(entity_id, {}) if entity_id else {}
				leaves = [{
					**component,
					"entity_type": "道具",
					"entity_id": entity_id,
					"entity_name": item.get("名称", ""),
					"resolved": bool(item),
					"source_file": self.item_sources.get(entity_id, ""),
					"reward_path": [reward_id],
				}]
			elif reward_type in REWARD_VALUE_TYPES:
				leaves = [{
					**component,
					"entity_type": reward_type.removeprefix("随机"),
					"entity_id": "",
					"entity_name": "",
					"resolved": True,
					"source_file": "",
					"reward_path": [reward_id],
				}]
			else:
				entity = self._entity_catalog(reward_type).get(entity_id, {}) if entity_id else {}
				leaves = [{
					**component,
					"entity_type": reward_type.removeprefix("随机") or "奖励",
					"entity_id": entity_id,
					"entity_name": entity.get("name", ""),
					"resolved": bool(entity),
					"source_file": entity.get("source_file", ""),
					"source_sheet": entity.get("sheet", ""),
					"reward_path": [reward_id],
				}]
			resolved_component.update({
				**component,
				"item_name": leaves[0].get("entity_name", "") if component["is_item"] and leaves else "",
				"item_resolved": leaves[0].get("resolved") if component["is_item"] and leaves else None,
				"item_source": leaves[0].get("source_file", "") if component["is_item"] and leaves else "",
				"leaf_rewards": leaves,
			})
			components.append(resolved_component)
		leaf_rewards = [leaf for component in components for leaf in component["leaf_rewards"]]
		return {
			"reward_id": reward_id,
			"description": row.get("随机奖励描述", ""),
			"components": components,
			"leaf_rewards": leaf_rewards,
			"resolved": bool(row),
			"source_file": self.reward_sources.get(reward_id, ""),
		}

	def condition_activity(self, row: Mapping[str, str]) -> Dict[str, object]:
		conditions = []
		unresolved_references = []
		for index in range(1, 16):
			prefix = f"条件{index}"
			fields = {
				"description": row.get(f"{prefix}简介", ""),
				"condition_type": row.get(f"{prefix}类型", ""),
				"target_value": row.get(f"{prefix}目标值", ""),
				"refresh_daily": row.get(f"{prefix}是否每日刷新", ""),
				"jump_entry": row.get(f"{prefix}跳转入口", ""),
			}
			parameters = [
				{"position": position, "value": row.get(f"{prefix}参数{position}", "")}
				for position in range(0, 6)
				if row.get(f"{prefix}参数{position}", "")
			]
			reward_id = row.get(f"{prefix}奖励ID", "")
			timed_reward_id = row.get(f"{prefix}限时奖励ID", "")
			if not any(fields.values()) and not parameters and not reward_id and not timed_reward_id:
				continue
			reward = self.reward(reward_id) if reward_id and reward_id not in {"0", "0x0"} else None
			timed_reward = (
				self.reward(timed_reward_id)
				if timed_reward_id and timed_reward_id not in {"0", "0x0"}
				else None
			)
			for role, resolved_reward in (("reward", reward), ("timed_reward", timed_reward)):
				if resolved_reward is not None and not resolved_reward["resolved"]:
					unresolved_references.append({
						"type": "random_reward",
						"id": resolved_reward["reward_id"],
						"path": f"{prefix}.{role}",
					})
				if resolved_reward is not None:
					for leaf in resolved_reward["leaf_rewards"]:
						if not leaf["resolved"]:
							unresolved_references.append({
								"type": leaf["entity_type"],
								"id": leaf["entity_id"],
								"path": f"{prefix}.{role}.reward{leaf.get('index', '')}",
							})
			conditions.append({
				"index": index,
				**fields,
				"parameters": parameters,
				"reward": reward,
				"timed_days": row.get(f"{prefix}限时天数", ""),
				"timed_reward": timed_reward,
			})
		return {
			"activity_id": row.get("活动ID", ""),
			"activity_name": row.get("活动名称") or row.get("活动标题", ""),
			"refresh_daily": row.get("是否每日刷新", ""),
			"trigger_type": row.get("条件触发类型", ""),
			"team_type": row.get("团队类型", ""),
			"purpose": row.get("条件活动目的", ""),
			"precondition_activity_id": row.get("前置条件活动ID", ""),
			"external_ilua": {
				"type": row.get("关联外部ilua活动类型", ""),
				"activity_id": row.get("关联外部ilua活动ID", ""),
			},
			"conditions": conditions,
			"unresolved_references": unresolved_references,
		}

	def sign_in_activity(self, row: Mapping[str, str]) -> Dict[str, object]:
		days = []
		unresolved_references = []
		for index in range(1, 33):
			reward_id = row.get(f"天数{index}奖励ID", "")
			bonus_mask = row.get(f"天数{index}奖励加成掩码", "")
			vip_level = row.get(f"天数{index}多倍VIP等级", "")
			preselection_id = row.get(f"天数{index}预选ID", "")
			if not any((reward_id, bonus_mask, vip_level, preselection_id)):
				continue
			reward = self.reward(reward_id) if reward_id and reward_id not in {"0", "0x0"} else None
			if reward is not None and not reward["resolved"]:
				unresolved_references.append({
					"type": "random_reward", "id": reward_id, "path": f"day{index}.reward",
				})
			if reward is not None:
				for leaf in reward["leaf_rewards"]:
					if not leaf["resolved"]:
						unresolved_references.append({
							"type": leaf["entity_type"],
							"id": leaf["entity_id"],
							"path": f"day{index}.reward.reward{leaf.get('index', '')}",
						})
			days.append({
				"index": index,
				"reward_id": reward_id,
				"reward": reward,
				"bonus_mask": bonus_mask,
				"multiple_vip_level": vip_level,
				"preselection_id": preselection_id,
			})
		return {
			"activity_id": row.get("活动ID", ""),
			"activity_name": row.get("活动名称") or row.get("活动标题", ""),
			"sign_in_type": row.get("签到类型", ""),
			"interruption_policy": row.get("中断处理类型", ""),
			"allow_makeup": row.get("是否可补签", ""),
			"makeup_price_id": row.get("补签价格ID", ""),
			"start_time": _format_compact_time(row.get("开始时间", "")),
			"end_time": _format_compact_time(row.get("结束时间", "")),
			"days": days,
			"unresolved_references": unresolved_references,
		}

	def text_activity(self, row: Mapping[str, str]) -> Dict[str, object]:
		linked_type = row.get("关联的活动类型", "")
		linked_id = row.get("关联的活动ID", "")
		linked_sheet = TEXT_LINKED_ACTIVITY_SHEETS.get(linked_type, linked_type)
		linked_row = next((
			candidate for candidate in self.daily_sheets.get(linked_sheet, [])
			if candidate.get("活动ID") == linked_id
		), None)
		linked_content = None
		if linked_row is not None and linked_sheet == CONDITION_ACTIVITY_SHEET:
			linked_content = {"kind": "condition_activity", "data": self.condition_activity(linked_row)}
		buttons = []
		for index in (1, 2):
			text_field = "按钮文字" if index == 1 else "按钮2文字"
			address_field = "按钮跳转地址" if index == 1 else "按钮2跳转地址"
			entry_field = "按钮跳转入口" if index == 1 else "按钮2跳转入口"
			if any((row.get(text_field, ""), row.get(address_field, ""), row.get(entry_field, ""))):
				buttons.append({
					"index": index,
					"text": row.get(text_field, ""),
					"address": row.get(address_field, ""),
					"entry": row.get(entry_field, ""),
				})
		return {
			"activity_id": row.get("活动ID", ""),
			"activity_name": row.get("活动名称") or row.get("活动标题", ""),
			"title": row.get("活动标题", ""),
			"description": row.get("活动简介", ""),
			"content": row.get("活动内容", ""),
			"image": row.get("活动图片", ""),
			"buttons": buttons,
			"linked_activity_type": linked_type,
			"linked_activity_id": linked_id,
			"linked_sheet": linked_sheet,
			"linked_resolved": bool(linked_row) if linked_id else None,
			"linked_activity": linked_content,
			"unresolved_references": ([{
				"type": "activity", "id": linked_id, "path": "linked_activity",
			}] if linked_id and linked_sheet != "ilua热更活动" and linked_row is None else []),
		}

	def exchange_object(self, object_type: str, object_id: str, quantity: str) -> Dict[str, object]:
		is_item = "道具" in object_type
		item = self.item_rows.get(object_id, {}) if is_item and object_id else {}
		return {
			"type": object_type,
			"id": object_id,
			"quantity": quantity,
			"is_item": is_item,
			"name": item.get("名称", ""),
			"resolved": bool(item) if is_item else None,
			"source_file": self.item_sources.get(object_id, "") if is_item else "",
		}

	def exchange_activity(self, rows: Sequence[Mapping[str, str]]) -> Dict[str, object]:
		exchanges = []
		unresolved_references = []
		for row in sorted(rows, key=lambda item: (item.get("活动索引", ""), item.get("序号id", ""))):
			output = self.exchange_object(
				row.get("兑换产出物品类型", ""),
				row.get("兑换产出物品ID", ""),
				row.get("兑换产出物品数量", ""),
			)
			costs = []
			for index in range(1, 6):
				cost = self.exchange_object(
					row.get(f"兑换收集物品{index}类型", ""),
					row.get(f"兑换收集物品{index}ID", ""),
					row.get(f"兑换收集物品{index}数量", ""),
				)
				if not any((cost["type"], cost["id"], cost["quantity"])):
					continue
				cost["position"] = index
				costs.append(cost)
			if output["is_item"] and output["id"] and not output["resolved"]:
				unresolved_references.append({
					"type": "item",
					"id": output["id"],
					"path": f"兑换项{row.get('活动索引', '')}.output",
				})
			for cost in costs:
				if cost["is_item"] and cost["id"] and not cost["resolved"]:
					unresolved_references.append({
						"type": "item",
						"id": cost["id"],
						"path": f"兑换项{row.get('活动索引', '')}.cost{cost['position']}",
					})
			exchanges.append({
				"sequence_id": row.get("序号id", ""),
				"activity_index": row.get("活动索引", ""),
				"name": row.get("活动名称") or row.get("活动标题", ""),
				"reset_daily": row.get("兑换次数是否日清", ""),
				"repeat_limit": row.get("重复兑换次数", ""),
				"reminder": row.get("兑换提醒", ""),
				"costs": costs,
				"output": output,
			})
		primary = rows[0] if rows else {}
		return {
			"activity_id": primary.get("活动ID", ""),
			"activity_name": primary.get("活动名称") or primary.get("活动标题", ""),
			"exchanges": exchanges,
			"unresolved_references": unresolved_references,
		}

	def collect_exchange_activity(self, row: Mapping[str, str]) -> Dict[str, object]:
		condition_activity_id = row.get("条件活动ID", "")
		exchange_activity_id = row.get("兑换活动ID", "")
		condition_rows = [
			item for item in self.daily_sheets.get(CONDITION_ACTIVITY_SHEET, [])
			if item.get("活动ID") == condition_activity_id
		]
		exchange_rows = [
			item for item in self.daily_sheets.get(EXCHANGE_ACTIVITY_SHEET, [])
			if item.get("活动ID") == exchange_activity_id
		]
		condition_tree = self.condition_activity(condition_rows[0]) if condition_rows else None
		exchange_tree = self.exchange_activity(exchange_rows) if exchange_rows else None
		unresolved_references = []
		if condition_activity_id and not condition_rows:
			unresolved_references.append({
				"type": "activity",
				"id": condition_activity_id,
				"sheet": CONDITION_ACTIVITY_SHEET,
				"path": "condition_activity",
			})
		if exchange_activity_id and not exchange_rows:
			unresolved_references.append({
				"type": "activity",
				"id": exchange_activity_id,
				"sheet": EXCHANGE_ACTIVITY_SHEET,
				"path": "exchange_activity",
			})
		for source, tree in (("condition_activity", condition_tree), ("exchange_activity", exchange_tree)):
			if tree is None:
				continue
			for unresolved in tree["unresolved_references"]:
				unresolved_references.append({**unresolved, "source": source})

		acquired_items = []
		if condition_tree is not None:
			for condition in condition_tree["conditions"]:
				for reward_role in ("reward", "timed_reward"):
					reward = condition.get(reward_role)
					if not isinstance(reward, Mapping):
						continue
					for component in reward.get("leaf_rewards", []):
						if component.get("entity_type") != "道具" or not component.get("entity_id"):
							continue
						acquired_items.append({
							"item_id": component["entity_id"],
							"item_name": component.get("entity_name", ""),
							"quantity_min": component.get("quantity_min", ""),
							"quantity_max": component.get("quantity_max", ""),
							"condition_index": condition["index"],
							"reward_role": reward_role,
							"reward_id": reward.get("reward_id", ""),
						})

		consumed_items = []
		output_items = []
		if exchange_tree is not None:
			for exchange in exchange_tree["exchanges"]:
				for cost in exchange["costs"]:
					if not cost.get("is_item") or not cost.get("id"):
						continue
					consumed_items.append({
						"item_id": cost["id"],
						"item_name": cost.get("name", ""),
						"quantity": cost.get("quantity", ""),
						"activity_index": exchange["activity_index"],
						"position": cost["position"],
					})
				output = exchange["output"]
				if output.get("is_item") and output.get("id"):
					output_items.append({
						"item_id": output["id"],
						"item_name": output.get("name", ""),
						"quantity": output.get("quantity", ""),
						"activity_index": exchange["activity_index"],
					})

		acquired_by_id: DefaultDict[str, List[Dict[str, object]]] = defaultdict(list)
		consumed_by_id: DefaultDict[str, List[Dict[str, object]]] = defaultdict(list)
		for item in acquired_items:
			acquired_by_id[str(item["item_id"])].append(item)
		for item in consumed_items:
			consumed_by_id[str(item["item_id"])].append(item)
		material_links = [
			{
				"item_id": item_id,
				"item_name": (
					str(acquired_by_id[item_id][0].get("item_name", ""))
					or str(consumed_by_id[item_id][0].get("item_name", ""))
				),
				"acquisition_paths": acquired_by_id[item_id],
				"consumption_paths": consumed_by_id[item_id],
			}
			for item_id in sorted(set(acquired_by_id) & set(consumed_by_id))
		]
		return {
			"activity_id": row.get("活动ID", ""),
			"activity_name": row.get("活动名称") or row.get("活动标题", ""),
			"condition_activity_id": condition_activity_id,
			"exchange_activity_id": exchange_activity_id,
			"condition_activity": condition_tree,
			"exchange_activity": exchange_tree,
			"material_flow": {
				"acquired_items": acquired_items,
				"consumed_items": consumed_items,
				"output_items": output_items,
				"links": material_links,
			},
			"unresolved_references": unresolved_references,
		}

	def active_point_activity(self, row: Mapping[str, str]) -> Dict[str, object]:
		condition_activity_id = row.get("关联的条件活动ID", "")
		condition_rows = [
			item for item in self.daily_sheets.get(CONDITION_ACTIVITY_SHEET, [])
			if item.get("活动ID") == condition_activity_id
		]
		condition_tree = self.condition_activity(condition_rows[0]) if condition_rows else None
		unresolved_references = []
		if condition_activity_id and not condition_rows:
			unresolved_references.append({
				"type": "activity",
				"id": condition_activity_id,
				"sheet": CONDITION_ACTIVITY_SHEET,
				"path": "condition_activity",
			})
		if condition_tree is not None:
			for unresolved in condition_tree["unresolved_references"]:
				unresolved_references.append({**unresolved, "source": "condition_activity"})
			for condition in condition_tree["conditions"]:
				condition["activity_points"] = row.get(
					f"活跃任务{condition['index']}活跃度数值",
					"",
				)

		tiers = []
		for tier_index in range(1, 6):
			requirement = row.get(f"第{tier_index}档活跃度要求", "")
			reward_id = row.get(f"第{tier_index}档奖励", "")
			if not requirement and not reward_id:
				continue
			reward = self.reward(reward_id) if reward_id and reward_id not in {"0", "0x0"} else None
			if reward is not None and not reward["resolved"]:
				unresolved_references.append({
					"type": "random_reward",
					"id": reward_id,
					"path": f"tier{tier_index}.reward",
				})
			if reward is not None:
				for component in reward["leaf_rewards"]:
					if not component["resolved"]:
						unresolved_references.append({
							"type": component["entity_type"],
							"id": component["entity_id"],
							"path": f"tier{tier_index}.reward.reward{component.get('index', '')}",
						})
			tiers.append({
				"index": tier_index,
				"requirement": requirement,
				"reward": reward,
			})

		return {
			"activity_id": row.get("活动ID", ""),
			"activity_name": row.get("活动名称") or row.get("活动标题", ""),
			"condition_activity_id": condition_activity_id,
			"condition_activity": condition_tree,
			"tiers": tiers,
			"mail_reward": row.get("是否邮件发送奖励", ""),
			"mail_title": row.get("邮件补发标题", ""),
			"mail_body": row.get("邮件补发正文", ""),
			"highest_reward_claim_time": _format_compact_time(row.get("最高奖励领取时间", "")),
			"unresolved_references": unresolved_references,
		}


def _selected_fields(row: Mapping[str, str], keywords: Iterable[str], limit: int = 30) -> Dict[str, str]:
	keywords = tuple(keywords)
	selected = {
		field: value
		for field, value in row.items()
		if value and any(keyword in field for keyword in keywords)
	}
	return dict(list(selected.items())[:limit])


def _format_compact_time(value: str) -> str:
	value = (value or "").strip()
	if len(value) == 14 and value.isdigit():
		return f"{value[0:4]}-{value[4:6]}-{value[6:8]} {value[8:10]}:{value[10:12]}:{value[12:14]}"
	return value


def _parse_compact_time(value: object) -> Optional[datetime]:
	text = str(value or "").strip()
	if len(text) != 14 or not text.isdigit():
		return None
	try:
		return datetime.strptime(text, "%Y%m%d%H%M%S")
	except ValueError:
		return None


def _format_impact_label(impact: Mapping[str, object]) -> str:
	trigger_type = str(impact.get("trigger_type", ""))
	trigger_id = str(impact.get("trigger_id", ""))
	via_reward_id = str(impact.get("via_reward_id", ""))
	if trigger_type == "activity":
		parts = [f"子活动 {trigger_id}"]
	elif trigger_type == "reward":
		parts = [f"奖励 {trigger_id}"]
	elif trigger_type == "entity":
		parts = [f"{impact.get('trigger_entity_type', '奖励实体')} {trigger_id}"]
		if via_reward_id:
			parts.append(f"奖励 {via_reward_id}")
	else:
		parts = [f"道具 {trigger_id}"]
		if via_reward_id:
			parts.append(f"奖励 {via_reward_id}")
	via_activity_id = str(impact.get("via_activity_id", ""))
	if via_activity_id:
		parts.append(f"{impact.get('child_sheet', '子活动')} {via_activity_id}")
	parts.append(str(impact.get("field", "")))
	return " → ".join(part for part in parts if part)


def _promotion_type(row: Mapping[str, str]) -> str:
	value = (row.get("是否可点券购买") or "").strip().casefold()
	return "直售" if value in {"1", "true", "yes", "是", "可购买", "开启"} else "限定"


def _find_navigation_value(value: object, names: Sequence[str]) -> str:
	if isinstance(value, Mapping):
		for key, item in value.items():
			if str(key).casefold() in names and str(item).strip():
				return str(item).strip()
		for item in value.values():
			found = _find_navigation_value(item, names)
			if found:
				return found
	if isinstance(value, list):
		for item in value:
			found = _find_navigation_value(item, names)
			if found:
				return found
	return ""


def _find_reference_ids(value: object, names: Sequence[str]) -> List[str]:
	results: List[str] = []
	if isinstance(value, Mapping):
		for key, item in value.items():
			if str(key).casefold() in names and str(item).strip():
				results.append(str(item).strip())
			results.extend(_find_reference_ids(item, names))
	elif isinstance(value, list):
		for item in value:
			results.extend(_find_reference_ids(item, names))
	return list(dict.fromkeys(results))


def _activity_reference_ids(row: Mapping[str, str]) -> List[str]:
	raw = (row.get("活动详情的json串") or "").strip()
	if not raw:
		return []
	try:
		parsed = json.loads(raw)
	except (TypeError, ValueError):
		return []
	return _find_reference_ids(parsed, ("activityid", "activity_id", "wealid", "weal_id"))


def _acquisition_method(row: Mapping[str, str]) -> Dict[str, str]:
	raw = (row.get("皮肤获取方式跳转入口") or "").strip()
	if not raw:
		return {"method": "未配置", "source": "empty", "raw": ""}
	parsed: object = raw
	try:
		parsed = json.loads(raw)
	except (TypeError, ValueError):
		pass
	url = _find_navigation_value(parsed, ("url", "link", "href"))
	if url or "http://" in raw.casefold() or "https://" in raw.casefold():
		return {"method": "H5获取", "source": "url", "value": url or raw, "raw": raw}
	form_id = _find_navigation_value(parsed, ("formid", "form_id", "form"))
	if form_id or "formid" in raw.casefold():
		return {
			"method": "待补充",
			"source": "form_id",
			"value": form_id,
			"raw": raw,
		}
	return {"method": "待补充", "source": "unknown", "raw": raw}


class SkinModule:
	id = "skin"
	name = "皮肤"
	file_name = "英雄皮肤促销表.dtxml"
	main_sheet = "svr下发皮肤上下架表"
	promotion_sheet = "svr下发皮肤促销特卖"
	client_promotion_sheet = "皮肤促销特卖"

	def matches(self, change: Mapping[str, object]) -> bool:
		return (
			change.get("file_name") == self.file_name
			and change.get("sheet") in {self.main_sheet, self.promotion_sheet}
		)

	def analyze(self, changes: Sequence[Mapping[str, object]], context: ModuleContext) -> Dict[str, object]:
		main_rows = _read_sheet(context, self.file_name, self.main_sheet)
		promotion_rows = _read_sheet(context, self.file_name, self.promotion_sheet)
		client_promotion_rows = _read_sheet(context, self.file_name, self.client_promotion_sheet)
		main_by_skin = {
			row.get("ID", ""): row
			for row in main_rows
			if row.get("ID")
		}
		promotion_by_id: Dict[str, tuple[Dict[str, str], str]] = {}
		for row in client_promotion_rows:
			if row.get("促销特卖ID"):
				promotion_by_id[row["促销特卖ID"]] = (row, self.client_promotion_sheet)
		for row in promotion_rows:
			if row.get("促销特卖ID"):
				promotion_by_id[row["促销特卖ID"]] = (row, self.promotion_sheet)
		changed_promotion_ids = {
			_row(change).get("促销特卖ID", "")
			for change in changes
			if change.get("sheet") == self.promotion_sheet and _row(change).get("促销特卖ID")
		}
		changed_skin_ids = set()
		for change in changes:
			row = _row(change)
			skin_id = row.get("ID") if change.get("sheet") == self.main_sheet else row.get("皮肤ID")
			if skin_id:
				changed_skin_ids.add(skin_id)

		items: List[Dict[str, object]] = []
		for skin_id in sorted(changed_skin_ids):
			main = main_by_skin.get(skin_id)
			if main is None:
				main = next((
					_row(change) for change in changes
					if change.get("sheet") == self.main_sheet
					and _row(change).get("ID") == skin_id
				), {})
			promotion_ids = [
				main.get(f"促销特卖{index}", "")
				for index in range(1, 6)
				if main.get(f"促销特卖{index}", "") not in {"", "0", "0x0"}
			]
			promotions = []
			unresolved_references = []
			for promotion_id in promotion_ids:
				resolved_promotion = promotion_by_id.get(promotion_id)
				if resolved_promotion is None:
					unresolved_references.append({
						"promotion_id": promotion_id,
						"searched_sheets": [self.promotion_sheet, self.client_promotion_sheet],
					})
					continue
				promotion, source_sheet = resolved_promotion
				promotion_type = _promotion_type(promotion)
				start_time = _format_compact_time(promotion.get("上架时间", ""))
				end_time = _format_compact_time(promotion.get("下架时间", ""))
				promotion_time = " 至 ".join(value for value in (start_time, end_time) if value)
				acquisition = _acquisition_method(promotion)
				hero_text = " ".join(value for value in (main.get("英雄ID", ""), main.get("英雄名", "")) if value)
				skin_text = " ".join(value for value in (skin_id, main.get("皮肤名称", "")) if value)
				display_lines = [
					f"英雄: {hero_text}",
					f"皮肤: {skin_text}",
					f"促销ID: {promotion_id}",
					f"促销类型: {promotion_type}",
					f"促销时间: {promotion_time}",
					f"获取方式: {acquisition['method']}",
				]
				promotions.append({
					"促销ID": promotion_id,
					"source_sheet": source_sheet,
					"changed_in_package": promotion_id in changed_promotion_ids,
					"促销类型": promotion_type,
					"促销开始时间": start_time,
					"促销结束时间": end_time,
					"促销时间": promotion_time,
					"获取方式": acquisition["method"],
					"获取方式解析": acquisition,
					"display_lines": display_lines,
					"display_text": "\n".join(display_lines),
					"fields": _selected_fields(
						promotion,
						("ID", "皮肤", "价格", "购买", "时间", "折扣", "促销", "获取", "排序"),
					),
				})
			item_changes = [
				_change_reference(change) for change in changes
				if (
					_row(change).get("ID")
					if change.get("sheet") == self.main_sheet
					else _row(change).get("皮肤ID")
				) == skin_id
			]
			items.append({
				"object_type": "skin_sale",
				"object_id": skin_id,
				"skin_id": main.get("皮肤ID", ""),
				"hero": {
					"id": main.get("英雄ID", ""),
					"name": main.get("英雄名", ""),
				},
				"skin": {
					"id": skin_id,
					"name": main.get("皮肤名称", ""),
				},
				"summary": f"皮肤 {skin_id} 的上下架或促销配置发生变化",
				"changes": item_changes,
				"current_state": _selected_fields(
					main,
					("ID", "英雄", "皮肤", "价格", "购买", "时间", "商店", "促销", "获取", "排序"),
				),
				"promotions": promotions,
				"unresolved_references": unresolved_references,
			})
		return {
			"module": self.id,
			"name": self.name,
			"status": "interpreted",
			"matched_change_count": len(changes),
			"item_count": len(items),
			"items": items,
			"warnings": [],
		}


class ActivityModule:
	id = "activity"
	name = "活动"
	files = {"日常活动表.dtxml", "157.ilua热更活动聚合配置表.dtxml"}

	def matches(self, change: Mapping[str, object]) -> bool:
		return change.get("file_name") in self.files

	def impact_matches(self, change: Mapping[str, object]) -> bool:
		file_name = str(change.get("file_name", ""))
		sheet_name = str(change.get("sheet", ""))
		return (
			(file_name in {RANDOM_REWARD_FILE, RANDOM_REWARD_FALLBACK_FILE} and sheet_name in RANDOM_REWARD_SHEETS)
			or bool(_reward_entity_changes(change))
		)

	def analyze(self, changes: Sequence[Mapping[str, object]], context: ModuleContext) -> Dict[str, object]:
		direct_changes = [change for change in changes if self.matches(change)]
		reference_index = ActivityReferenceIndex(context)
		impacts_by_activity = reference_index.impacts_for_changes(changes)
		groups: Dict[str, List[Mapping[str, object]]] = {}
		for change in direct_changes:
			row = _row(change)
			activity_id = row.get("活动ID") or _business_key_value(change, "活动ID") or _business_key(change)
			groups.setdefault(activity_id, []).append(change)
		for activity_id in impacts_by_activity:
			groups.setdefault(activity_id, [])
		sheet_cache: Dict[tuple[str, str], List[Dict[str, str]]] = {}
		daily_sheets = reference_index.daily_sheets
		items = []
		for activity_id, grouped in sorted(groups.items()):
			activity_impacts = impacts_by_activity.get(activity_id, [])
			states = []
			locations = sorted({
				(str(change.get("file_name", "")), str(change.get("sheet", "")))
				for change in grouped
			})
			context_rows: List[tuple[str, str, Dict[str, str]]] = []
			for file_name, sheet_name in locations:
				cache_key = (file_name, sheet_name)
				if cache_key not in sheet_cache:
					sheet_cache[cache_key] = _read_sheet(context, file_name, sheet_name)
				matched_rows = [
					row for row in sheet_cache[cache_key]
					if row.get("活动ID") == activity_id
				]
				context_rows.extend((file_name, sheet_name, row) for row in matched_rows)
			for impact in activity_impacts:
				impact_sheet = str(impact.get("sheet", ""))
				matched_impact_rows = [
					row for row in daily_sheets.get(impact_sheet, [])
					if row.get("活动ID") == activity_id
				]
				if not matched_impact_rows and isinstance(impact.get("row"), dict):
					matched_impact_rows = [impact["row"]]
				for impact_row in matched_impact_rows:
					candidate = ("日常活动表.dtxml", impact_sheet, impact_row)
					if candidate not in context_rows:
						context_rows.append(candidate)
			if not context_rows and grouped:
				context_rows = [
					(str(change.get("file_name", "")), str(change.get("sheet", "")), _row(change))
					for change in grouped
				]
			for file_name, sheet_name, row in context_rows:
				states.append({
					"file_name": file_name,
					"sheet": sheet_name,
					"fields": _selected_fields(
						row,
						("ID", "名称", "标题", "类型", "时间", "入口", "奖励", "条件", "状态", "图片"),
					),
				})
			primary = context_rows[0][2] if context_rows else (_row(grouped[0]) if grouped else {})
			activity_name = primary.get("活动名称") or primary.get("活动标题", "")
			start_time = _format_compact_time(primary.get("开始时间", ""))
			end_time = _format_compact_time(primary.get("结束时间", ""))
			activity_time = " 至 ".join(value for value in (start_time, end_time) if value)
			reference_ids = _activity_reference_ids(primary)
			related_activities = []
			for reference_id in reference_ids:
				for sheet_name, rows in daily_sheets.items():
					for row in rows:
						if row.get("活动ID") != reference_id:
							continue
						related_activities.append({
							"activity_id": reference_id,
							"name": row.get("活动名称") or row.get("活动标题", ""),
							"file_name": "日常活动表.dtxml",
							"sheet": sheet_name,
							"fields": _selected_fields(
								row,
								("ID", "名称", "标题", "类型", "时间", "入口", "奖励", "条件", "状态", "图片", "索引"),
							),
						})
			related_labels = list(dict.fromkeys(
				f"{item['activity_id']} {item['name']} ({item['sheet']})".strip()
				for item in related_activities
			))
			display_lines = [
				f"活动: {' '.join(value for value in (activity_id, activity_name) if value)}",
				f"配置类型: {', '.join(sorted({sheet for _, sheet, _ in context_rows}))}",
				f"活动时间: {activity_time}",
				f"活动入口: {primary.get('活动入口', '')}",
				f"本次直接变化: {len(grouped)} 条",
			]
			impact_labels = list(dict.fromkeys(_format_impact_label(impact) for impact in activity_impacts))
			if impact_labels:
				display_lines.append(f"间接影响: {'; '.join(impact_labels)}")
			if related_labels:
				display_lines.append(f"关联活动: {'; '.join(related_labels)}")
			condition_row = next((
				row for _, sheet_name, row in context_rows
				if sheet_name == CONDITION_ACTIVITY_SHEET
			), None)
			activity_content: Dict[str, object] = {
				"kind": "not_implemented",
				"sheet": context_rows[0][1] if context_rows else "",
			}
			if condition_row is not None:
				condition_tree = reference_index.condition_activity(condition_row)
				direct_changed_fields = {
					str(field)
					for change in grouped
					if change.get("sheet") == CONDITION_ACTIVITY_SHEET
					for field in change.get("changed_fields", [])
				}
				for condition in condition_tree["conditions"]:
					prefix = f"条件{condition['index']}"
					condition["change_context"] = {
						"direct_fields": sorted(
							field for field in direct_changed_fields if field.startswith(prefix)
						),
						"indirect_impacts": [
							{key: value for key, value in impact.items() if key != "row"}
							for impact in activity_impacts
							if str(impact.get("condition_index", "")) == str(condition["index"])
						],
					}
				activity_content = {
					"kind": "condition_activity",
					"sheet": CONDITION_ACTIVITY_SHEET,
					"data": condition_tree,
				}
				display_lines.append(f"条件数量: {len(condition_tree['conditions'])}")
				for condition in condition_tree["conditions"]:
					reward = condition.get("reward")
					reward_label = ""
					if isinstance(reward, Mapping):
						leaf_labels = _reward_leaf_labels(reward)
						reward_label = ", ".join(leaf_labels) or str(reward.get("reward_id", ""))
					display_lines.append(
						f"条件{condition['index']}: {condition['description']}"
						f" | 目标 {condition['target_value']}"
						f" | 每日刷新 {condition['refresh_daily'] or '未配置'}"
						f" | 奖励 {reward_label}"
					)
			else:
				exchange_rows = [
					row for _, sheet_name, row in context_rows
					if sheet_name == EXCHANGE_ACTIVITY_SHEET
				]
				if exchange_rows:
					exchange_tree = reference_index.exchange_activity(exchange_rows)
					changed_fields_by_index: DefaultDict[str, List[str]] = defaultdict(list)
					for change in grouped:
						if change.get("sheet") != EXCHANGE_ACTIVITY_SHEET:
							continue
						changed_row = _row(change)
						exchange_index = (
							changed_row.get("活动索引")
							or _business_key_value(change, "活动索引")
						)
						changed_fields_by_index[exchange_index].extend(
							str(field) for field in change.get("changed_fields", [])
						)
					for exchange in exchange_tree["exchanges"]:
						exchange["change_context"] = {
							"direct_fields": sorted(set(changed_fields_by_index[exchange["activity_index"]])),
							"indirect_impacts": [
								{key: value for key, value in impact.items() if key != "row"}
								for impact in activity_impacts
								if str(impact.get("exchange_index", "")) == str(exchange["activity_index"])
							],
						}
					activity_content = {
						"kind": "exchange_activity",
						"sheet": EXCHANGE_ACTIVITY_SHEET,
						"data": exchange_tree,
					}
					display_lines.append(f"兑换项数量: {len(exchange_tree['exchanges'])}")
					for exchange in exchange_tree["exchanges"]:
						cost_labels = [
							f"{cost['type']} {' '.join(value for value in (str(cost['id']), str(cost['name'])) if value)} ×{cost['quantity']}"
							for cost in exchange["costs"]
						]
						output = exchange["output"]
						output_label = (
							f"{output['type']} {' '.join(value for value in (str(output['id']), str(output['name'])) if value)}"
							f" ×{output['quantity']}"
						)
						display_lines.append(
							f"兑换项{exchange['activity_index']}: {' + '.join(cost_labels)} → {output_label}"
							f" | 每日清零 {exchange['reset_daily'] or '未配置'}"
							f" | 次数 {exchange['repeat_limit'] or '未配置'}"
						)
				else:
					collect_row = next((
						row for _, sheet_name, row in context_rows
						if sheet_name == COLLECT_EXCHANGE_ACTIVITY_SHEET
					), None)
					if collect_row is not None:
						collect_tree = reference_index.collect_exchange_activity(collect_row)
						collect_tree["change_context"] = {
							"direct_fields": sorted({
								str(field)
								for change in grouped
								if change.get("sheet") == COLLECT_EXCHANGE_ACTIVITY_SHEET
								for field in change.get("changed_fields", [])
							}),
							"indirect_impacts": [
								{key: value for key, value in impact.items() if key != "row"}
								for impact in activity_impacts
							],
						}
						activity_content = {
							"kind": "collect_exchange_activity",
							"sheet": COLLECT_EXCHANGE_ACTIVITY_SHEET,
							"data": collect_tree,
						}
						display_lines.extend([
							f"材料获取活动: {collect_tree['condition_activity_id']}",
							f"材料兑换活动: {collect_tree['exchange_activity_id']}",
							f"获取道具记录: {len(collect_tree['material_flow']['acquired_items'])} 条",
							f"消耗道具记录: {len(collect_tree['material_flow']['consumed_items'])} 条",
						])
						for link in collect_tree["material_flow"]["links"]:
								display_lines.append(
								f"材料关联: {' '.join(value for value in (link['item_id'], link['item_name']) if value)}"
								f" | 获取路径 {len(link['acquisition_paths'])}"
									f" | 消耗路径 {len(link['consumption_paths'])}"
								)
					else:
						active_row = next((
							row for _, sheet_name, row in context_rows
							if sheet_name == ACTIVE_POINT_ACTIVITY_SHEET
						), None)
						if active_row is not None:
							active_tree = reference_index.active_point_activity(active_row)
							direct_fields = sorted({
								str(field)
								for change in grouped
								if change.get("sheet") == ACTIVE_POINT_ACTIVITY_SHEET
								for field in change.get("changed_fields", [])
							})
							active_tree["change_context"] = {
								"direct_fields": direct_fields,
								"indirect_impacts": [
									{key: value for key, value in impact.items() if key != "row"}
									for impact in activity_impacts
								],
							}
							condition_tree = active_tree.get("condition_activity")
							if isinstance(condition_tree, Mapping):
								for condition in condition_tree.get("conditions", []):
									condition["change_context"] = {
										"direct_fields": sorted(
											field for field in direct_fields
											if field == f"活跃任务{condition['index']}活跃度数值"
										),
										"indirect_impacts": [
											{key: value for key, value in impact.items() if key != "row"}
											for impact in activity_impacts
											if str(impact.get("condition_index", "")) == str(condition["index"])
										],
									}
							for tier in active_tree["tiers"]:
								tier["change_context"] = {
									"direct_fields": sorted(
										field for field in direct_fields
										if field.startswith(f"第{tier['index']}档")
									),
									"indirect_impacts": [
										{key: value for key, value in impact.items() if key != "row"}
										for impact in activity_impacts
										if str(impact.get("tier_index", "")) == str(tier["index"])
									],
								}
							activity_content = {
								"kind": "active_point_activity",
								"sheet": ACTIVE_POINT_ACTIVITY_SHEET,
								"data": active_tree,
							}
							display_lines.append(f"关联条件活动: {active_tree['condition_activity_id']}")
							if isinstance(condition_tree, Mapping):
								for condition in condition_tree.get("conditions", []):
									display_lines.append(
										f"活跃任务{condition['index']}: {condition['description']}"
										f" | 活跃度 {condition['activity_points'] or '未配置'}"
									)
							for tier in active_tree["tiers"]:
								reward = tier.get("reward")
								reward_label = ""
								if isinstance(reward, Mapping):
									reward_label = ", ".join(_reward_leaf_labels(reward)) or str(reward.get("reward_id", ""))
									display_lines.append(
										f"第{tier['index']}档: {tier['requirement']} 活跃度 → 奖励 {reward_label}"
									)
			if activity_content["kind"] == "not_implemented":
				sign_in_row = next((
					row for _, sheet_name, row in context_rows
					if sheet_name == SIGN_IN_ACTIVITY_SHEET
				), None)
				text_row = next((
					row for _, sheet_name, row in context_rows
					if sheet_name == TEXT_ACTIVITY_SHEET
				), None)
				if sign_in_row is not None:
					sign_in_tree = reference_index.sign_in_activity(sign_in_row)
					direct_fields = sorted({
						str(field)
						for change in grouped
						if change.get("sheet") == SIGN_IN_ACTIVITY_SHEET
						for field in change.get("changed_fields", [])
					})
					for day in sign_in_tree["days"]:
						day["change_context"] = {
							"direct_fields": [
								field for field in direct_fields if field.startswith(f"天数{day['index']}")
							],
							"indirect_impacts": [
								{key: value for key, value in impact.items() if key != "row"}
								for impact in activity_impacts
								if str(impact.get("day_index", "")) == str(day["index"])
							],
						}
					activity_content = {
						"kind": "sign_in_activity",
						"sheet": SIGN_IN_ACTIVITY_SHEET,
						"data": sign_in_tree,
					}
					display_lines.append(
						f"签到类型: {sign_in_tree['sign_in_type'] or '未配置'}"
						f" | 中断处理 {sign_in_tree['interruption_policy'] or '未配置'}"
						f" | 可补签 {sign_in_tree['allow_makeup'] or '未配置'}"
					)
					for day in sign_in_tree["days"]:
						reward = day.get("reward")
						reward_label = ""
						if isinstance(reward, Mapping):
							reward_label = ", ".join(_reward_leaf_labels(reward)) or str(day["reward_id"])
						display_lines.append(f"第{day['index']}天: {reward_label}")
				elif text_row is not None:
					text_tree = reference_index.text_activity(text_row)
					text_tree["change_context"] = {
						"direct_fields": sorted({
							str(field)
							for change in grouped
							if change.get("sheet") == TEXT_ACTIVITY_SHEET
							for field in change.get("changed_fields", [])
						}),
						"indirect_impacts": [
							{key: value for key, value in impact.items() if key != "row"}
							for impact in activity_impacts
						],
					}
					activity_content = {
						"kind": "text_activity",
						"sheet": TEXT_ACTIVITY_SHEET,
						"data": text_tree,
					}
					if text_tree["description"]:
						display_lines.append(f"活动简介: {text_tree['description']}")
					for button in text_tree["buttons"]:
						destination = button["entry"] or button["address"]
						display_lines.append(f"按钮{button['index']}: {button['text']} → {destination}")
					if text_tree["linked_activity_id"]:
						display_lines.append(
							f"关联活动: {text_tree['linked_activity_type']} {text_tree['linked_activity_id']}"
						)
					linked = text_tree.get("linked_activity")
					if isinstance(linked, Mapping) and linked.get("kind") == "condition_activity":
						for condition in linked["data"]["conditions"]:
							reward = condition.get("reward")
							reward_label = ", ".join(_reward_leaf_labels(reward)) if isinstance(reward, Mapping) else ""
							display_lines.append(
								f"关联条件{condition['index']}: {condition['description']}"
								f" | 目标 {condition['target_value']} | 奖励 {reward_label}"
							)
			reward_ids = list(dict.fromkeys(
				str(impact["via_reward_id"]) for impact in activity_impacts if impact.get("via_reward_id")
			))
			items.append({
				"object_type": "activity",
				"object_id": activity_id,
				"name": activity_name,
				"activity_type": context_rows[0][1] if context_rows else "",
				"summary": (
					f"活动 {activity_id}{f'（{activity_name}）' if activity_name else ''}"
					f"涉及 {len(grouped)} 条直接变化、{len(activity_impacts)} 条关联影响"
				),
				"display_lines": display_lines,
				"display_text": "\n".join(display_lines),
				"changes": [
					{
						**_change_reference(change),
						"field_changes": _field_change_details(change),
					}
					for change in grouped
				],
				"impact_reasons": [
					{key: value for key, value in impact.items() if key != "row"}
					for impact in activity_impacts
				],
				"affected_rewards": [reference_index.reward(reward_id) for reward_id in reward_ids],
				"activity_content": activity_content,
				"current_state": states,
				"reference_ids": reference_ids,
				"related_activities": related_activities,
			})
		return {
			"module": self.id,
			"name": self.name,
			"status": "interpreted",
			"matched_change_count": len(direct_changes),
			"impact_trigger_count": len(changes) - len(direct_changes),
			"item_count": len(items),
			"items": items,
			"warnings": [],
		}


class RewardModule:
	id = "reward"
	name = "奖励"

	def matches(self, change: Mapping[str, object]) -> bool:
		return (
			change.get("file_name") == RANDOM_REWARD_FILE
			and change.get("sheet") in RANDOM_REWARD_SHEETS
		)

	def analyze(self, changes: Sequence[Mapping[str, object]], context: ModuleContext) -> Dict[str, object]:
		index = ActivityReferenceIndex(context)
		items = []
		for change in changes:
			for reward_id in _changed_values(change, "随机奖励ID"):
				reward = index.reward(reward_id)
				leaf_labels = _reward_leaf_labels(reward)
				display_lines = [
					f"奖励: {' '.join(value for value in (reward_id, str(reward['description'])) if value)}",
					f"最终内容: {', '.join(leaf_labels) if leaf_labels else '未解析到奖励内容'}",
					f"本次变化: {change.get('change_type', '')}",
				]
				items.append({
					"object_type": "random_reward",
					"object_id": reward_id,
					"name": reward["description"],
					"summary": f"随机奖励 {reward_id} 配置发生变化",
					"display_lines": display_lines,
					"display_text": "\n".join(display_lines),
					"changes": [{
						**_change_reference(change),
						"field_changes": _field_change_details(change),
					}],
					"current_state": reward,
				})
		return {
			"module": self.id,
			"name": self.name,
			"status": "interpreted",
			"matched_change_count": len(changes),
			"item_count": len(items),
			"items": items,
			"warnings": [],
		}


class OutputLimitModule:
	id = "output_limit"
	name = "产出限量"
	FILE_NAME = "48.礼包产出控制表.dtxml"
	SHEETS = {"礼包产出控制", "礼包产出控制新"}

	def matches(self, change: Mapping[str, object]) -> bool:
		return change.get("file_name") == self.FILE_NAME and change.get("sheet") in self.SHEETS

	@staticmethod
	def _limit_slots(row: Mapping[str, str], reward: Mapping[str, object]) -> List[Dict[str, object]]:
		components = reward.get("components", []) if isinstance(reward.get("components"), list) else []
		slots = []
		for index in range(1, 21):
			limits = {
				"daily_limit": row.get(f"指定物品{index}每日上限", ""),
				"total_limit": row.get(f"指定物品{index}总上限", ""),
				"control_interval": row.get(f"指定物品{index}控制间隔", ""),
				"interval_output_limit": row.get(f"指定物品{index}控制间隔产出上限", ""),
			}
			if not any(limits.values()):
				continue
			component = components[index - 1] if index <= len(components) and isinstance(components[index - 1], Mapping) else {}
			leaf_rewards = component.get("leaf_rewards", []) if isinstance(component.get("leaf_rewards"), list) else []
			slots.append({
				"slot_index": index,
				**limits,
				"reward_type": str(component.get("type", "")),
				"reward_id": str(component.get("item_id", "")),
				"quantity_min": str(component.get("quantity_min", "")),
				"quantity_max": str(component.get("quantity_max", "")),
				"leaf_rewards": [dict(leaf) for leaf in leaf_rewards if isinstance(leaf, Mapping)],
				"reward_slot_resolved": bool(component),
			})
		return slots

	@staticmethod
	def _callers(reward_id: str, index: ActivityReferenceIndex) -> Dict[str, object]:
		gift_items = [
			{
				"item_id": item_id,
				"item_name": row.get("名称", ""),
				"category": row.get("类型", ""),
			}
			for item_id, row in index.item_rows.items()
			if row.get("效果参数1") == reward_id and "礼包" in row.get("类型", "")
		]
		activities = [
			{
				"activity_id": str(activity.get("activity_id", "")),
				"activity_name": str(activity.get("activity_name", "")),
				"sheet": str(activity.get("sheet", "")),
				"field": str(activity.get("field", "")),
			}
			for activity in index.reward_to_activities.get(reward_id, [])
		]
		parent_rewards = []
		for parent_id, parent_row in index.reward_rows.items():
			if any(
				component.get("type") == "随机嵌套" and component.get("item_id") == reward_id
				for component in _reward_components(parent_row)
			):
				parent_rewards.append(parent_id)
		return {
			"gift_items": gift_items,
			"activities": activities,
			"parent_reward_ids": parent_rewards,
		}

	def analyze(self, changes: Sequence[Mapping[str, object]], context: ModuleContext) -> Dict[str, object]:
		index = ActivityReferenceIndex(context)
		grouped: DefaultDict[str, List[Mapping[str, object]]] = defaultdict(list)
		for change in changes:
			reward_id = _row(change).get("随机奖励ID") or _business_key_value(change, "随机奖励ID")
			if not reward_id:
				reward_id = _business_key(change).removeprefix("随机奖励ID=")
			grouped[reward_id].append(change)

		items = []
		for reward_id, reward_changes in grouped.items():
			row = next((_row(change) for change in reversed(reward_changes) if _row(change)), {})
			reward = index.reward(reward_id)
			limit_slots = self._limit_slots(row, reward)
			callers = self._callers(reward_id, index)
			source_sheets = list(dict.fromkeys(str(change.get("sheet", "")) for change in reward_changes))
			display_lines = [
				f"限量随机奖励: {reward_id} {reward.get('description', '')}".rstrip(),
				f"来源页签: {', '.join(source_sheets)}",
			]
			caller_labels = [
				f"礼包道具 {item['item_id']} {item['item_name']}".rstrip()
				for item in callers["gift_items"]
			]
			caller_labels.extend(
				f"{activity['sheet']} {activity['activity_id']} {activity['activity_name']}".rstrip()
				for activity in callers["activities"]
			)
			caller_labels.extend(f"嵌套奖励 {parent_id}" for parent_id in callers["parent_reward_ids"])
			display_lines.append(f"调用位置: {', '.join(caller_labels) if caller_labels else '未找到已识别调用方'}")
			for slot in limit_slots:
				leaf_labels = _reward_leaf_labels({"leaf_rewards": slot["leaf_rewards"]})
				reward_label = ", ".join(leaf_labels) or " ".join(
					value for value in (slot["reward_type"], slot["reward_id"]) if value
				) or "未解析到奖励内容"
				limit_labels = [
					f"每日上限={slot['daily_limit']}" if slot["daily_limit"] else "",
					f"总上限={slot['total_limit']}" if slot["total_limit"] else "",
					f"控制间隔={slot['control_interval']}" if slot["control_interval"] else "",
					f"间隔产出上限={slot['interval_output_limit']}" if slot["interval_output_limit"] else "",
				]
				display_lines.append(f"奖励{slot['slot_index']}: {reward_label}")
				display_lines.append(f"限量: {' | '.join(label for label in limit_labels if label)}")
			items.append({
				"object_type": "output_limit",
				"object_id": reward_id,
				"name": str(reward.get("description", "")),
				"summary": f"随机奖励 {reward_id} 有 {len(limit_slots)} 个限量槽位",
				"display_lines": display_lines,
				"display_text": "\n".join(display_lines),
				"changes": [{**_change_reference(change), "field_changes": _field_change_details(change)} for change in reward_changes],
				"source_sheets": source_sheets,
				"reward": reward,
				"limit_slots": limit_slots,
				"limited_slot_count": len(limit_slots),
				"callers": callers,
				"current_state": row,
			})
		return {
			"module": self.id,
			"name": self.name,
			"status": "interpreted",
			"matched_change_count": len(changes),
			"item_count": len(items),
			"limited_slot_count": sum(int(item["limited_slot_count"]) for item in items),
			"items": items,
			"warnings": [],
		}


class ItemModule:
	id = "item"
	name = "道具"
	DEFERRED_CATEGORIES = {
		"装备进阶材料",
		"英雄战技经验礼包",
		"英雄升星材料",
		"英雄进阶材料",
		"数值道具",
		"自走棋棋手激活道具",
		"自走棋抽奖券",
		"自走棋棋手碎片",
		"自走棋活跃代币",
		"月卡和周卡",
		"门票类(不可主动使用、不可出售)",
		"扫荡券",
	}

	CATEGORY_PURPOSES = {
		"普通道具": "作为活动进度 Token；通过活动奖励获得，并在兑换或进度活动中使用",
		"数值道具": "使用后改变对应数值",
		"礼包道具": "可开启礼包；礼包内容由效果参数和关联配置决定",
		"延后领取礼包": "开启后进入延后领取流程；具体内容由延后领取礼包配置决定",
		"延后领用礼包": "开启后进入延后领取流程；具体内容由延后领取礼包配置决定",
		"活动抽奖礼包": "用于活动抽奖礼包的开启或发奖；内容由活动抽奖批次、奖池和随机奖励共同决定",
		"头像道具": "使用后获得头像资源",
		"头像框资源": "使用后获得头像框资源",
		"单局特效": "使用后获得对应时限或永久单局特效",
		"快捷消息": "使用后获得快捷消息资源",
		"次元部件道具": "用于次元部件资源",
		"次元主题道具": "用于次元主题资源",
		"VALORPASS积分卡": "使用后增加 VALORPASS 积分",
		"VP通行证": "用于开通或升级 VP 通行证",
		"小应用云积分": "用于增加小应用云积分",
		"限定点券": "作为限定点券使用",
		"亲密度礼物": "赠送后增加好友亲密度，并播放对应礼物展示效果",
		"抵价券": "购买指定范围商品时抵扣固定点券金额",
		"折扣券": "购买指定范围商品时按比例折扣",
		"满减抵价券": "满足价格条件后抵扣固定点券金额",
		"满减折扣券": "满足价格条件后按比例折扣",
		"预选礼包": "开启后从预选择配置的候选内容中选择奖励",
		"体验卡": "限时解锁英雄或皮肤；已拥有时按配置发放补偿",
		"夺宝抽奖券": "作为常驻夺宝或活动抽奖的抽取消耗道具",
		"月卡和周卡": "该类型已记录并预留，当前版本不进行权益解析",
		"喇叭道具": "用于全服聊天频道或大厅顶部的跨玩家消息展示",
		"排位守护卡": "在满足对应排位赛结算条件时提供加星效果",
		"系统语音": "解锁对应的局内系统语音资源",
	}

	REFERENCE_ROLE_LABELS = {
		"random_reward": "作为随机奖励内容",
		"activity_reward": "作为活动奖励发放",
		"exchange_cost": "作为兑换消耗材料",
		"exchange_output": "作为兑换产出",
		"gift_content": "礼包内容配置",
		"delay_gift_content": "延后领取礼包内容配置",
		"quick_message_content": "快捷消息内容配置",
		"item_resource_content": "道具资源配置",
		"activity_draw_config": "活动抽奖批次与奖池配置",
		"preselection_config": "预选择礼包配置",
		"token_progress_config": "活动 Token 进度配置",
		"trial_card_target": "体验卡目标资源",
		"trial_card_conversion": "体验卡自动转换道具",
		"treasure_draw_config": "夺宝抽奖消耗配置",
		"loudspeaker_config": "喇叭展示配置",
		"system_voice_config": "系统语音配置",
	}

	@staticmethod
	def _hidden_item_state(row: Mapping[str, str]) -> Dict[str, object]:
		raw_value = str(row.get("是否是隐藏道具", "")).strip()
		normalized = raw_value.casefold()
		if normalized in {"1", "是", "true", "yes"}:
			status = "hidden"
			is_hidden = True
		elif normalized in {"0", "否", "false", "no"}:
			status = "visible"
			is_hidden = False
		elif not normalized:
			status = "default_visible"
			is_hidden = False
		else:
			status = "unknown"
			is_hidden = False
		return {
			"field": "是否是隐藏道具",
			"raw_value": raw_value,
			"status": status,
			"is_hidden": is_hidden,
			"needs_attention": status in {"hidden", "unknown"},
		}

	def matches(self, change: Mapping[str, object]) -> bool:
		file_name = str(change.get("file_name", ""))
		return (
			(
				fnmatch(file_name, "41.svr下发道具信息表*.dtxml")
				or fnmatch(file_name, "【运营配置】41.道具信息表*.dtxml")
			)
			and change.get("sheet") in {"道具信息", "道具信息增量"}
		)

	@staticmethod
	def _references(
		item_id: str,
		changes: Sequence[Mapping[str, object]],
		reference_index: ActivityReferenceIndex,
		category_usage: Mapping[str, object],
	) -> List[Dict[str, object]]:
		references: List[Dict[str, object]] = []
		for reward_id in reference_index.item_to_rewards.get(item_id, []):
			reward = reference_index.reward_rows.get(reward_id, {})
			for component in _reward_components(reward):
				if not component.get("is_item") or str(component.get("item_id", "")) != item_id:
					continue
				references.append({
					"role": "random_reward",
					"direction": "inbound",
					"file_name": reference_index.reward_sources.get(reward_id, ""),
					"sheet": "随机奖励配置表",
					"business_id": reward_id,
					"field": f"奖励{component['index']}ID",
				})

		category_reference = category_usage.get("reference")
		if isinstance(category_reference, Mapping):
			references.append(dict(category_reference))
		category_references = category_usage.get("references")
		if isinstance(category_references, Sequence) and not isinstance(category_references, (str, bytes)):
			references.extend(dict(reference) for reference in category_references if isinstance(reference, Mapping))

		for activity_id, impacts in reference_index.impacts_for_changes(changes).items():
			for impact in impacts:
				role = "activity_reward"
				if impact.get("exchange_role") == "cost":
					role = "exchange_cost"
				elif impact.get("exchange_role") == "output":
					role = "exchange_output"
				references.append({
					"role": role,
					"direction": "inbound",
					"file_name": "日常活动表.dtxml",
					"sheet": str(impact.get("sheet", "")),
					"business_id": activity_id,
					"business_name": str(impact.get("activity_name", "")),
					"field": str(impact.get("field", "")),
					"activity_start_time": str(impact.get("row", {}).get("开始时间", "")),
					"activity_end_time": str(impact.get("row", {}).get("结束时间", "")),
				})

		unique: List[Dict[str, object]] = []
		seen = set()
		for reference in references:
			key = tuple(str(reference.get(field, "")) for field in (
				"role", "file_name", "sheet", "business_id", "field",
			))
			if key not in seen:
				seen.add(key)
				unique.append(reference)
		return unique

	@staticmethod
	def _category_usage(row: Mapping[str, str], reference_index: ActivityReferenceIndex) -> Dict[str, object]:
		category = row.get("类型", "")
		config_id = row.get("效果参数1", "")
		base = {
			"category": category,
			"config_id": config_id,
			"effect_parameters": [
				{"index": index, "value": row.get(f"效果参数{index}", "")}
				for index in range(1, 6)
				if row.get(f"效果参数{index}", "")
			],
		}
		if category == "普通道具":
			item_id = row.get("ID", "")
			progress = reference_index.token_progress(item_id)
			synthetic_change = {
				"file_name": "41.svr下发道具信息表_Syndra.dtxml",
				"sheet": "道具信息",
				"business_key": {"display": f"ID={item_id}"},
				"before": None,
				"after": row,
			}
			impacts = [
				impact
				for activity_impacts in reference_index.impacts_for_changes([synthetic_change]).values()
				for impact in activity_impacts
			]

			def activity_summary(impact: Mapping[str, object], relation: str) -> Dict[str, object]:
				activity_row = impact.get("row", {})
				if not isinstance(activity_row, Mapping):
					activity_row = {}
				return {
					"relation": relation,
					"activity_id": str(impact.get("activity_id", "")),
					"activity_name": str(impact.get("activity_name", "")),
					"activity_type": ACTIVITY_TYPE_LABELS.get(str(impact.get("sheet", "")), str(impact.get("sheet", ""))),
					"sheet": str(impact.get("sheet", "")),
					"field": str(impact.get("field", "")),
					"fields": [str(impact.get("field", ""))] if impact.get("field") else [],
					"activity_index": str(impact.get("exchange_index", "")),
					"via_reward_id": str(impact.get("via_reward_id", "")),
					"via_reward_ids": [str(impact.get("via_reward_id", ""))] if impact.get("via_reward_id") else [],
					"via_activity_id": str(impact.get("via_activity_id", "")),
					"start_time": _format_compact_time(str(activity_row.get("开始时间", ""))),
					"end_time": _format_compact_time(str(activity_row.get("结束时间", ""))),
				}

			acquisition_activities = []
			consumption_activities = []
			related_activities = []
			seen = set()
			for impact in impacts:
				if impact.get("via_activity_id"):
					relation = "parent"
					target = related_activities
				elif impact.get("exchange_role") == "cost":
					relation = "consumption"
					target = consumption_activities
				else:
					relation = "acquisition"
					target = acquisition_activities
				summary = activity_summary(impact, relation)
				key = (
					relation,
					summary["sheet"],
					summary["activity_id"],
					summary["activity_index"] if summary["sheet"] == EXCHANGE_ACTIVITY_SHEET else "",
					"" if relation in {"parent", "acquisition"} else summary["field"],
				)
				if key in seen:
					existing = next((activity for activity in target if (
						activity["sheet"] == summary["sheet"]
						and activity["activity_id"] == summary["activity_id"]
						and (
							activity["activity_index"] == summary["activity_index"]
							if summary["sheet"] == EXCHANGE_ACTIVITY_SHEET else True
						)
					)), None)
					if existing:
						for field in summary["fields"]:
							if field not in existing["fields"]:
								existing["fields"].append(field)
						for reward_id in summary["via_reward_ids"]:
							if reward_id not in existing["via_reward_ids"]:
								existing["via_reward_ids"].append(reward_id)
					continue
				seen.add(key)
				target.append(summary)
			has_progress = bool(progress["activities"] or progress["ilua_activities"])
			has_consumption = bool(consumption_activities)
			if has_progress and has_consumption:
				business_mode = "hybrid"
			elif has_progress:
				business_mode = "progress_counter"
			elif has_consumption:
				business_mode = "exchange_currency"
			elif acquisition_activities:
				business_mode = "acquisition_only"
			else:
				business_mode = "unresolved"
			progress_references = [
				{
					"role": "token_progress_config",
					"direction": "outbound",
					"file_name": "159.通用条件配置表.dtxml",
					"sheet": "通用条件配置表",
					"business_id": condition["condition_id"],
					"field": "参数2",
				}
				for condition in progress["conditions"]
			]
			progress_references.extend({
				"role": "token_progress_config",
				"direction": "outbound",
				"file_name": "日常活动表.dtxml",
				"sheet": activity["sheet"],
				"business_id": activity["activity_id"],
				"field": "活动_通用条件",
				"activity_start_time": activity["start_time_raw"],
				"activity_end_time": activity["end_time_raw"],
			} for activity in progress["activities"])
			progress_references.extend({
				"role": "token_progress_config",
				"direction": "outbound",
				"file_name": "157.ilua热更活动聚合配置表.dtxml",
				"sheet": activity["sheet"],
				"business_id": activity["activity_id"],
				"field": "活动详情的json串.tokenID",
			} for activity in progress["ilua_activities"])
			return {
				**base,
				"config_id": item_id,
				"kind": "activity_token",
				"resolved": bool(impacts or has_progress),
				"content": {
					"token_id": item_id,
					"token_name": row.get("名称", ""),
					"business_mode": business_mode,
					"progress_conditions": progress["conditions"],
					"progress_activities": progress["activities"],
					"ilua_activities": progress["ilua_activities"],
					"acquisition_activities": acquisition_activities,
					"consumption_activities": consumption_activities,
					"related_activities": related_activities,
					"acquisition_activity_count": len(acquisition_activities),
					"consumption_activity_count": len(consumption_activities),
					"related_activity_count": len(related_activities),
				},
				"references": progress_references,
			}
		if category in ItemModule.DEFERRED_CATEGORIES:
			return {
				**base,
				"kind": "deferred_category",
				"resolved": True,
				"content": {
					"category": category,
					"status": "reserved",
					"reason": "该业务类型已预留，当前版本暂不进行专用解析",
				},
			}
		if category == "体验卡":
			card_type = row.get("效果参数1", "")
			target_id = row.get("效果参数2", "")
			days = row.get("效果参数3", "")
			hours = row.get("小时体验卡时间", "")
			if hours and hours not in {"0", "0.0"}:
				duration_value = hours
				duration_unit = "hour"
				duration_label = f"{hours}小时"
			else:
				duration_value = days
				duration_unit = "day"
				duration_label = f"{days}天" if days else "未配置"
			target_type = "皮肤" if "皮肤" in card_type else "英雄" if "英雄" in card_type else card_type.removesuffix("体验卡")
			entity_catalog_type = "随机皮肤" if target_type == "皮肤" else "随机英雄" if target_type == "英雄" else ""
			entity = reference_index._entity_catalog(entity_catalog_type).get(target_id, {}) if entity_catalog_type else {}
			configured_target_name = str(entity.get("name", ""))
			card_name = row.get("名称", "")
			description = row.get("描述", "")
			name_mismatch = bool(
				configured_target_name
				and configured_target_name != "未命名"
				and description
				and configured_target_name not in description
			)
			if not configured_target_name or configured_target_name == "未命名" or name_mismatch:
				target_name = card_name
				target_name_source = "trial_card"
			else:
				target_name = configured_target_name
				target_name_source = "entity_catalog"
			conversion_item_id = row.get("可自动转换道具ID", "")
			conversion_item = reference_index.item_catalog.rows.get(conversion_item_id, {}) if conversion_item_id else {}
			references = []
			if target_id:
				references.append({
					"role": "trial_card_target",
					"direction": "outbound",
					"file_name": entity.get("source_file", ""),
					"sheet": entity.get("sheet", ""),
					"business_id": target_id,
					"field": "效果参数2",
				})
			if conversion_item_id:
				references.append({
					"role": "trial_card_conversion",
					"direction": "outbound",
					"file_name": reference_index.item_catalog.sources.get(conversion_item_id, ""),
					"sheet": reference_index.item_catalog.source_sheets.get(conversion_item_id, ""),
					"business_id": conversion_item_id,
					"field": "可自动转换道具ID",
				})
			return {
				**base,
				"config_id": target_id,
				"kind": "trial_card",
				"resolved": bool(target_id) and bool(entity) and bool(duration_value),
				"content": {
					"card_type": card_type,
					"target_type": target_type,
					"target_id": target_id,
					"target_name": target_name,
					"configured_target_name": configured_target_name,
					"target_name_source": target_name_source,
					"target_name_mismatch": name_mismatch,
					"duration_value": duration_value,
					"duration_unit": duration_unit,
					"duration_label": duration_label,
					"owned_compensation_diamonds": row.get("使用获取的钻石数量", ""),
					"auto_conversion": {
						"item_id": conversion_item_id,
						"item_name": conversion_item.get("名称", ""),
						"quantity": row.get("可自动转换道具数量", ""),
						"resolved": bool(conversion_item),
					},
				},
				"references": references,
			}
		if category == "夺宝抽奖券":
			item_id = row.get("ID", "")
			lucky_file = "幸运夺宝表.dtxml"
			lucky_sheets = _read_all_sheets(reference_index.context, lucky_file)
			draw_configs = []
			for draw_row in lucky_sheets.get("夺宝配置", []):
				draw_options = []
				for index in range(1, 11):
					if draw_row.get(f"[抽奖类型]{index}消耗道具ID") != item_id:
						continue
					draw_options.append({
						"index": index,
						"draw_type": draw_row.get(f"[抽奖类型]{index}类型", ""),
						"cost_item_id": item_id,
						"cost_quantity": draw_row.get(f"[抽奖类型]{index}消耗道具个数", ""),
					})
				if not draw_options:
					continue
				draw_id = draw_row.get("ID", "")
				pool_batches = []
				for batch_row in lucky_sheets.get("奖池批次", []):
					if batch_row.get("夺宝ID") != draw_id:
						continue
					pool_id = batch_row.get("奖池ID", "")
					rewards = []
					for reward_row in lucky_sheets.get("奖励池设定", []):
						if reward_row.get("奖励池ID") != pool_id:
							continue
						reward_type = reward_row.get("物品类型", "")
						entity_id = reward_row.get("物品ID", "")
						if reward_type == "随机道具":
							entity = reference_index.item_catalog.rows.get(entity_id, {})
							entity_name = entity.get("名称", "")
						elif entity_id:
							entity = reference_index._entity_catalog(reward_type).get(entity_id, {})
							entity_name = entity.get("name", "")
						else:
							entity = {}
							entity_name = reward_type.removeprefix("随机")
						rewards.append({
							"index": reward_row.get("奖励序号", ""),
							"entity_type": reward_type.removeprefix("随机"),
							"entity_id": entity_id,
							"entity_name": entity_name,
							"quantity": reward_row.get("物品数量", ""),
							"probability_per_10000": reward_row.get("物品概率", ""),
							"prize_grade": reward_row.get("大奖品级ID", ""),
							"resolved": bool(entity_name),
						})
					pool_batches.append({
						"pool_id": pool_id,
						"start_time": _format_compact_time(batch_row.get("开始时间", "")),
						"end_time": _format_compact_time(batch_row.get("结束时间", "")),
						"reward_count": len(rewards),
						"total_probability_per_10000": sum(
							int(reward["probability_per_10000"])
							for reward in rewards if str(reward["probability_per_10000"]).isdigit()
						),
						"rewards": rewards,
					})
				pool_batches.sort(key=lambda batch: str(batch["start_time"]))
				draw_configs.append({
					"draw_id": draw_id,
					"draw_label": draw_row.get("夺宝标签", "").removeprefix("夺宝标签_"),
					"enabled": draw_row.get("是否开启", ""),
					"start_time": _format_compact_time(draw_row.get("开始时间", "")),
					"end_time": _format_compact_time(draw_row.get("结束时间", "")),
					"rare_min_draws": draw_row.get("抽中稀有物品最少次数", ""),
					"rare_max_draws": draw_row.get("抽中稀有物品最大次数", ""),
					"draw_options": draw_options,
					"pool_batches": pool_batches,
					"latest_pool": pool_batches[-1] if pool_batches else {},
				})

			activity_draw_file = "97.莉莉安魔法抽奖表.dtxml"
			activity_draws = []
			for sheet_name, rows in _read_all_sheets(reference_index.context, activity_draw_file).items():
				for activity_row in rows:
					if activity_row.get("货币消耗类型") != item_id:
						continue
					activity_draws.append({
						"sheet": sheet_name,
						"draw_id": activity_row.get("抽奖ID", ""),
						"draw_type": activity_row.get("抽奖类型", ""),
						"activity_name": activity_row.get("活动名字") or activity_row.get("活动页签", ""),
						"start_time": _format_compact_time(activity_row.get("开始时间", "")),
						"end_time": _format_compact_time(activity_row.get("结束时间", "")),
						"cost_quantity": activity_row.get("货币消耗值", ""),
						"pool_id": activity_row.get("奖励池ID", ""),
						"multi_draw_count": activity_row.get("连抽数量", ""),
					})
			if draw_configs and activity_draws:
				business_mode = "multi_system"
			elif draw_configs:
				business_mode = "standard_treasure"
			elif activity_draws:
				business_mode = "activity_draw"
			else:
				business_mode = "inactive_or_unresolved"
			references = [
				{
					"role": "treasure_draw_config",
					"direction": "outbound",
					"file_name": lucky_file,
					"sheet": "夺宝配置",
					"business_id": draw["draw_id"],
					"field": "[抽奖类型]N消耗道具ID",
				}
				for draw in draw_configs
			]
			references.extend({
				"role": "treasure_draw_config",
				"direction": "outbound",
				"file_name": activity_draw_file,
				"sheet": draw["sheet"],
				"business_id": draw["draw_id"],
				"field": "货币消耗类型",
			} for draw in activity_draws)
			return {
				**base,
				"config_id": item_id,
				"kind": "treasure_draw_ticket",
				"resolved": bool(draw_configs or activity_draws),
				"content": {
					"ticket_id": item_id,
					"ticket_name": row.get("名称", ""),
					"business_mode": business_mode,
					"standard_draws": draw_configs,
					"activity_draws": activity_draws,
				},
				"references": references,
			}
		if category == "喇叭道具":
			effect_id = row.get("效果参数1", "")
			file_name = "【运营配置】41.道具信息表_Syndra.dtxml"
			sheet_name = "喇叭信息"
			config_row = next((
				item for item in _read_sheet(reference_index.context, file_name, sheet_name)
				if item.get("ID") == effect_id
			), {})
			loudspeaker_type = config_row.get("喇叭类型", "")
			display_scope = {
				"小喇叭": "全服聊天频道",
				"大喇叭": "大厅顶部全区展示",
			}.get(loudspeaker_type, "未识别")
			return {
				**base,
				"config_id": effect_id,
				"kind": "loudspeaker",
				"resolved": bool(config_row),
				"content": {
					"config_id": effect_id,
					"loudspeaker_type": loudspeaker_type,
					"display_scope": display_scope,
					"character_limit": config_row.get("字数限制", ""),
					"minimum_display_seconds": config_row.get("最小显示时间", ""),
					"maximum_display_seconds": config_row.get("最大显示时间", ""),
					"effect_parameter_2_code": row.get("效果参数2", ""),
				},
				"reference": {
					"role": "loudspeaker_config",
					"direction": "outbound",
					"file_name": file_name,
					"sheet": sheet_name,
					"business_id": effect_id,
					"field": "效果参数1",
				},
			}
		if category == "排位守护卡":
			item_id = row.get("ID", "")
			duration_hours = row.get("限时道具有效期", "")
			duration_days = ""
			try:
				hours_value = float(duration_hours)
				if hours_value > 0 and hours_value % 24 == 0:
					duration_days = f"{hours_value / 24:g}"
			except (TypeError, ValueError):
				pass
			return {
				**base,
				"config_id": item_id,
				"kind": "rank_protection_card",
				"resolved": bool(row.get("效果参数1", "")),
				"content": {
					"card_id": item_id,
					"card_name": row.get("名称", ""),
					"effect_type": row.get("效果参数1", ""),
					"effect_parameter_2_code": row.get("效果参数2", ""),
					"validity_hours": duration_hours,
					"validity_days": duration_days,
					"available_start_time": _format_compact_time(row.get("可使用开始日期", "")),
					"available_end_time": _format_compact_time(row.get("可使用结束日期", "")),
				},
			}
		if category == "系统语音" and config_id:
			file_name = "【运营配置】局内交流配置表.dtxml"
			definitions = []
			for sheet_name, source_kind, priority in (
				("系统语音配置", "client", 10),
				("svr系统语音配置", "server", 30),
			):
				voice_row = next((
					item for item in _read_sheet(reference_index.context, file_name, sheet_name)
					if item.get("ID") == config_id
				), {})
				if voice_row:
					definitions.append({
						"priority": priority,
						"source_kind": source_kind,
						"sheet": sheet_name,
						"row": voice_row,
					})
			selected = max(definitions, key=lambda item: int(item["priority"])) if definitions else {}
			voice_row = selected.get("row", {}) if isinstance(selected.get("row"), Mapping) else {}
			previews = [
				{
					"index": index,
					"title": voice_row.get(f"试听{index}标题", ""),
					"event": voice_row.get(f"试听{index}事件", ""),
				}
				for index in range(1, 4)
				if voice_row.get(f"试听{index}标题", "") or voice_row.get(f"试听{index}事件", "")
			]
			start_time = voice_row.get("开始时间", "")
			end_time = voice_row.get("结束时间", "")
			return {
				**base,
				"kind": "system_voice",
				"resolved": bool(selected),
				"content": {
					"voice_id": config_id,
					"title": voice_row.get("标题", ""),
					"subtitle": voice_row.get("副标题", ""),
					"cv": voice_row.get("CV", ""),
					"acquisition_description": voice_row.get("获取途径描述", ""),
					"dlc_type": voice_row.get("DLC类型名", ""),
					"bank_resource": voice_row.get("Bank资源", ""),
					"start_time": "" if start_time in {"", "0"} else _format_compact_time(start_time),
					"end_time": "" if end_time in {"", "0"} else _format_compact_time(end_time),
					"closed_code": voice_row.get("是否关闭", ""),
					"previews": previews,
					"source_kind": selected.get("source_kind", ""),
					"source_sheet": selected.get("sheet", ""),
					"available_sources": [item["source_kind"] for item in definitions],
				},
				"reference": {
					"role": "system_voice_config",
					"direction": "outbound",
					"file_name": file_name,
					"sheet": selected.get("sheet", "系统语音配置"),
					"business_id": config_id,
					"field": "效果参数1",
				},
			}
		if category == "礼包道具" and config_id:
			reward = reference_index.reward(config_id)
			return {
				**base,
				"kind": "random_reward_gift",
				"resolved": reward["resolved"],
				"content": reward,
				"reference": {
					"role": "gift_content",
					"direction": "outbound",
					"file_name": reward.get("source_file", ""),
					"sheet": "随机奖励配置表",
					"business_id": config_id,
					"field": "效果参数1",
				},
			}
		if category in {"延后领取礼包", "延后领用礼包"} and config_id:
			file_name = ""
			sheet_name = ""
			config_row: Dict[str, str] = {}
			if reference_index.context.tdr_root:
				common_core = reference_index.context.dtxml_path("placeholder.dtxml").parent
				for path in sorted(common_core.glob("140.*礼包配置表.dtxml")):
					sheets = _read_all_sheets(reference_index.context, path.name)
					for candidate_sheet in sorted(sheets, key=lambda name: ("服务器下发" not in name, name)):
						if "延后" not in candidate_sheet or "礼包配置表" not in candidate_sheet:
							continue
						candidate = next((
							item for item in sheets[candidate_sheet]
							if (item.get("延后领取礼包ID") or item.get("延后领用礼包ID")) == config_id
						), {})
						if candidate:
							file_name = path.name
							sheet_name = candidate_sheet
							config_row = candidate
							break
					if config_row:
						break
			if not file_name:
				file_name = "140.延后领用礼包配置表.dtxml"
				sheet_name = "服务器下发延后领用礼包配置表"
			choices = []
			for index in range(1, 51):
				reward_type = config_row.get(f"奖励{index}类型", "")
				entity_id = config_row.get(f"奖励{index}ID", "")
				quantity = config_row.get(f"奖励{index}数量", "")
				if not any((reward_type, entity_id, quantity)):
					continue
				entity = reference_index._entity_catalog(reward_type).get(entity_id, {}) if entity_id else {}
				choices.append({
					"index": index,
					"type": reward_type.removeprefix("随机") or reward_type,
					"id": entity_id,
					"name": entity.get("name", ""),
					"quantity": quantity,
					"resolved": bool(entity),
				})
			return {
				**base,
				"kind": "delay_draw_gift",
				"resolved": bool(config_row),
				"content": {
					"description": config_row.get("延后领取礼包描述") or config_row.get("延后领用礼包描述", ""),
					"select_count": config_row.get("可选个数", ""),
					"auto_open": config_row.get("是否自动打开", ""),
					"choices": choices,
				},
				"reference": {
					"role": "delay_gift_content",
					"direction": "outbound",
					"file_name": file_name,
					"sheet": sheet_name,
					"business_id": config_id,
					"field": "效果参数1",
				},
			}
		if category == "活动抽奖礼包":
			batch_id = row.get("效果参数1", "")
			lottery_file = "活动抽奖表.dtxml"
			base_sheet = ""
			batch_row: Dict[str, str] = {}
			pool_rows_by_sheet: Dict[str, List[Dict[str, str]]] = {}
			if reference_index.context.tdr_root:
				sheets = _read_all_sheets(reference_index.context, lottery_file)
				for candidate_sheet in ("svr下发基础信息", "基础信息"):
					candidate = next((item for item in sheets.get(candidate_sheet, []) if item.get("批次ID") == batch_id), {})
					if candidate:
						base_sheet = candidate_sheet
						batch_row = candidate
						break
				pool_rows_by_sheet = {
					candidate_sheet: sheets.get(candidate_sheet, [])
					for candidate_sheet in ("svr下发奖励池", "奖励池")
				}

			pool_specs = []
			main_pool_id = batch_row.get("主奖池ID", "")
			if main_pool_id:
				pool_specs.append({"role": "main", "label": "主奖池", "pool_id": main_pool_id})
			for index in range(1, 6):
				pool_id = batch_row.get(f"保底{index}奖励池ID", "")
				if pool_id:
					pool_specs.append({
						"role": f"guarantee_{index}",
						"label": f"保底{index}",
						"pool_id": pool_id,
						"required_draws": batch_row.get(f"保底{index}必得抽数", ""),
						"guarantee_type": batch_row.get(f"保底{index}类型", ""),
						"deduplicate": batch_row.get(f"保底{index}开启去重", ""),
						"repeatable": batch_row.get(f"保底{index}是否循环保底", ""),
					})
			for index in range(1, 6):
				pool_id = batch_row.get(f"区间{index}奖励池ID", "")
				if pool_id:
					pool_specs.append({
						"role": f"interval_{index}",
						"label": f"区间{index}",
						"pool_id": pool_id,
						"draw_count": batch_row.get(f"区间{index}抽数", ""),
					})

			pools = []
			for pool_spec in pool_specs:
				pool_id = str(pool_spec["pool_id"])
				selected_pool_sheet = ""
				selected_pool_rows: List[Dict[str, str]] = []
				for candidate_sheet in ("svr下发奖励池", "奖励池"):
					candidates = [
						pool_row for pool_row in pool_rows_by_sheet.get(candidate_sheet, [])
						if pool_row.get("奖励池ID") == pool_id
					]
					if candidates:
						selected_pool_sheet = candidate_sheet
						selected_pool_rows = candidates
						break
				rewards = []
				for pool_row in selected_pool_rows:
					reward_id = pool_row.get("奖励ID", "")
					reward = reference_index.reward(reward_id) if reward_id else {}
					rewards.append({
						"sequence": pool_row.get("奖励序号", ""),
						"reward_id": reward_id,
						"weight": pool_row.get("权重", ""),
						"globally_limited": pool_row.get("是否全服限量", ""),
						"reward_level": pool_row.get("奖励等级", ""),
						"reward": reward,
					})
				pools.append({
					**pool_spec,
					"source_sheet": selected_pool_sheet,
					"rewards": rewards,
					"reward_group_count": len(rewards),
					"final_reward_count": sum(len(reward["reward"].get("leaf_rewards", [])) for reward in rewards),
				})

			return {
				**base,
				"config_id": batch_id,
				"kind": "activity_draw_gift",
				"resolved": bool(batch_row) and bool(pools) and all(pool["rewards"] for pool in pools),
				"content": {
					"batch_id": batch_id,
					"rule_id": batch_row.get("规则ID", ""),
					"main_pool_deduplicate": batch_row.get("是否开启主奖池去重", ""),
					"pools": pools,
					"pool_count": len(pools),
					"reward_group_count": sum(pool["reward_group_count"] for pool in pools),
					"final_reward_count": sum(pool["final_reward_count"] for pool in pools),
				},
				"references": [
					{
						"role": "activity_draw_config",
						"direction": "outbound",
						"file_name": lottery_file,
						"sheet": base_sheet,
						"business_id": batch_id,
						"field": "效果参数1",
					},
					*[
						{
							"role": "activity_draw_config",
							"direction": "outbound",
							"file_name": lottery_file,
							"sheet": str(pool["source_sheet"]),
							"business_id": str(pool["pool_id"]),
							"field": str(pool["label"]),
						}
						for pool in pools
					],
				],
			}
		if category == "快捷消息" and config_id:
			file_name = ""
			message_sheet = ""
			message_row: Dict[str, str] = {}
			theme_sheet = ""
			theme_row: Dict[str, str] = {}
			if reference_index.context.tdr_root:
				common_core = reference_index.context.dtxml_path("placeholder.dtxml").parent
				for path in sorted(common_core.glob("*局内交流配置表.dtxml")):
					sheets = _read_all_sheets(reference_index.context, path.name)
					for candidate_sheet in ("svr预定义文本", "预定义文本"):
						candidate = next((
							item for item in sheets.get(candidate_sheet, []) if item.get("ID") == config_id
						), {})
						if candidate:
							file_name = path.name
							message_sheet = candidate_sheet
							message_row = candidate
							break
					if message_row:
						theme_id = message_row.get("快捷消息主题ID", "")
						for candidate_sheet in ("svr快捷消息主题配置", "快捷消息主题配置"):
							candidate = next((
								item for item in sheets.get(candidate_sheet, []) if item.get("ID") == theme_id
							), {})
							if candidate:
								theme_sheet = candidate_sheet
								theme_row = candidate
								break
						break
			if not file_name:
				file_name = "【运营配置】局内交流配置表.dtxml"
				message_sheet = "svr预定义文本"
			return {
				**base,
				"kind": "quick_message",
				"resolved": bool(message_row),
				"content": {
					"message_id": config_id,
					"text": message_row.get("文本内容", ""),
					"display_type": message_row.get("显示类型", ""),
					"channel_id": message_row.get("所属频道ID", ""),
					"channel_name": message_row.get("所属频道标题", ""),
					"theme_id": message_row.get("快捷消息主题ID", ""),
					"theme_entry_id": message_row.get("快捷消息条目ID", ""),
					"theme_name": theme_row.get("主题名称", ""),
					"theme_start_time": _format_compact_time(theme_row.get("开始时间", "")),
					"theme_end_time": _format_compact_time(theme_row.get("结束时间", "")),
					"theme_resolved": bool(theme_row),
				},
				"reference": {
					"role": "quick_message_content",
					"direction": "outbound",
					"file_name": file_name,
					"sheet": message_sheet,
					"business_id": config_id,
					"field": "效果参数1",
					"theme_sheet": theme_sheet,
				},
			}
		if category == "单局特效":
			effect_id = row.get("效果参数2", "")
			duration_days = row.get("效果参数3", "")
			definitions: List[Dict[str, object]] = []
			listings: List[Dict[str, object]] = []
			if reference_index.context.tdr_root and effect_id:
				regional_core = reference_index.context.dtxml_path("placeholder.dtxml").parent
				definition_paths = [
					*sorted(regional_core.glob("*88.局内特效配置表.dtxml")),
					*sorted((Path(reference_index.context.tdr_root) / "Xml" / "CommonCore").glob("88.*局内特效配置表.dtxml")),
				]
				for path in definition_paths:
					sheets = _read_all_sheets_path(path)
					for sheet_name, priority, source_kind in (
						("局内特效配置表", 20 if path.parent == regional_core else 10, "client" if path.parent == regional_core else "base"),
						("svr局内特效配置表", 30, "server"),
					):
						effect_row = next((item for item in sheets.get(sheet_name, []) if item.get("特效ID") == effect_id), {})
						if effect_row:
							definitions.append({
								"priority": priority,
								"source_kind": source_kind,
								"file_name": path.name,
								"sheet": sheet_name,
								"row": effect_row,
							})

				for path in sorted(regional_core.glob("89.局内特效上下架与促销表.dtxml")):
					sheets = _read_all_sheets_path(path)
					for sheet_name, priority, source_kind in (
						("局内特效上下架表", 10, "client"),
						("svr局内特效上下架表", 30, "server"),
					):
						listing_row = next((item for item in sheets.get(sheet_name, []) if item.get("局内特效ID") == effect_id), {})
						if listing_row:
							listings.append({
								"priority": priority,
								"source_kind": source_kind,
								"file_name": path.name,
								"sheet": sheet_name,
								"row": listing_row,
							})

			definitions.sort(key=lambda item: int(item["priority"]), reverse=True)
			listings.sort(key=lambda item: int(item["priority"]), reverse=True)

			def first_value(entries: Sequence[Mapping[str, object]], field: str) -> str:
				for entry in entries:
					entry_row = entry.get("row", {})
					if isinstance(entry_row, Mapping) and entry_row.get(field):
						return str(entry_row[field])
				return ""

			selected_definition = definitions[0] if definitions else {}
			selected_listing = listings[0] if listings else {}
			duration_label = f"{duration_days} 天" if duration_days and duration_days != "0" else "永久"
			return {
				**base,
				"config_id": effect_id,
				"kind": "battle_effect",
				"resolved": bool(definitions or listings),
				"content": {
					"effect_id": effect_id,
					"effect_type": first_value(definitions, "特效类型"),
					"effect_name": first_value(listings, "特效名称") or first_value(definitions, "特效名称"),
					"description": first_value(listings, "特效描述") or first_value(definitions, "特效描述"),
					"duration_days": duration_days,
					"duration_label": duration_label,
					"hero_scope": first_value(definitions, "英雄适用范围"),
					"mode_scope": first_value(definitions, "模式适用范围"),
					"resource_file": first_value(definitions, "资源文件"),
					"included_in_package": first_value(definitions, "是否进包"),
					"listed_at": _format_compact_time(first_value(listings, "上架时间")),
					"delisted_at": _format_compact_time(first_value(listings, "下架时间")),
					"purchasable": first_value(listings, "是否可购买"),
					"currency": first_value(listings, "购买货币类型"),
					"price": first_value(listings, "价格"),
					"definition_source_kind": selected_definition.get("source_kind", ""),
					"listing_source_kind": selected_listing.get("source_kind", ""),
					"available_definition_sources": [
						{
							"source_kind": entry["source_kind"],
							"file_name": entry["file_name"],
							"sheet": entry["sheet"],
						}
						for entry in definitions
					],
					"available_listing_sources": [
						{
							"source_kind": entry["source_kind"],
							"file_name": entry["file_name"],
							"sheet": entry["sheet"],
						}
						for entry in listings
					],
				},
				"reference": {
					"role": "item_resource_content",
					"direction": "outbound",
					"file_name": selected_definition.get("file_name", "") or selected_listing.get("file_name", ""),
					"sheet": selected_definition.get("sheet", "") or selected_listing.get("sheet", ""),
					"business_id": effect_id,
					"field": "效果参数2",
				},
			}
		if category == "次元部件道具":
			part_ids = []
			for index in (2, 3, 1):
				candidate = row.get(f"效果参数{index}", "")
				if candidate.isdigit() and len(candidate) >= 5 and candidate not in part_ids:
					part_ids.append(candidate)
			part_rows: Dict[str, Dict[str, str]] = {}
			listing_entries: DefaultDict[str, List[Dict[str, object]]] = defaultdict(list)
			part_file = "次元部件表.dtxml"
			if reference_index.context.tdr_root:
				base_core = Path(reference_index.context.tdr_root) / "Xml" / "CommonCore"
				part_sheets = _read_all_sheets_path(base_core / part_file)
				for part_row in part_sheets.get("次元部件表", []):
					part_id = part_row.get("部件ID", "")
					if part_id in part_ids:
						part_rows[part_id] = part_row

				regional_core = reference_index.context.dtxml_path("placeholder.dtxml").parent
				for path in sorted(regional_core.glob("*次元上下架与促销表.dtxml")):
					sheets = _read_all_sheets_path(path)
					for sheet_name, priority, source_kind in (
						("次元部件上下架表", 10, "client"),
						("svr次元部件上下架表", 30, "server"),
					):
						for listing_row in sheets.get(sheet_name, []):
							part_id = listing_row.get("次元部件或主题ID", "")
							if part_id in part_ids and listing_row.get("是否是主题", "") not in {"1", "是"}:
								listing_entries[part_id].append({
									"priority": priority,
									"source_kind": source_kind,
									"file_name": path.name,
									"sheet": sheet_name,
									"row": listing_row,
								})

			part_type_labels = {
				"1": "发型", "2": "头", "3": "上半身", "4": "下半身",
				"5": "连体衣", "6": "头套", "7": "耳环", "8": "面饰",
				"9": "背饰", "10": "手环", "11": "武器",
			}
			gender_labels = {"1": "男", "2": "女"}
			parts = []
			for part_id in part_ids:
				part_row = part_rows.get(part_id, {})
				listings = sorted(listing_entries.get(part_id, []), key=lambda item: int(item["priority"]), reverse=True)
				selected_listing = listings[0] if listings else {}
				listing_row = selected_listing.get("row", {})
				if not isinstance(listing_row, Mapping):
					listing_row = {}
				parts.append({
					"part_id": part_id,
					"gender": gender_labels.get(part_row.get("性别", ""), part_row.get("性别", "")),
					"part_type": part_type_labels.get(part_row.get("类型", ""), part_row.get("类型", "")),
					"subtype": part_row.get("子类型", ""),
					"name": listing_row.get("名称") or part_row.get("名称", ""),
					"description": listing_row.get("描述") or part_row.get("描述", ""),
					"icon": part_row.get("图标", ""),
					"mapped_gender_part_id": part_row.get("映射性转id", ""),
					"release_id": part_row.get("投放ID", ""),
					"listed_at": _format_compact_time(str(listing_row.get("上架时间", ""))),
					"delisted_at": _format_compact_time(str(listing_row.get("下架时间", ""))),
					"purchasable": listing_row.get("是否可购买", ""),
					"currency": listing_row.get("购买货币类型", ""),
					"price": listing_row.get("价格", ""),
					"listing_source_kind": selected_listing.get("source_kind", ""),
				})
			return {
				**base,
				"config_id": ",".join(part_ids),
				"kind": "dimensional_parts",
				"resolved": bool(parts) and all(part_id in part_rows for part_id in part_ids),
				"content": {
					"gender_mode": row.get("效果参数1", ""),
					"parts": parts,
				},
				"references": [
					{
						"role": "item_resource_content",
						"direction": "outbound",
						"file_name": part_file,
						"sheet": "次元部件表",
						"business_id": part_id,
						"field": "效果参数2" if index == 0 else "效果参数3",
					}
					for index, part_id in enumerate(part_ids)
				],
			}
		if category == "次元主题道具":
			theme_ids = []
			for index in (2, 3, 1):
				candidate = row.get(f"效果参数{index}", "")
				if candidate.isdigit() and candidate not in theme_ids:
					theme_ids.append(candidate)
			theme_rows: Dict[str, Dict[str, str]] = {}
			part_rows: Dict[str, Dict[str, str]] = {}
			listing_entries: DefaultDict[str, List[Dict[str, object]]] = defaultdict(list)
			if reference_index.context.tdr_root:
				base_core = Path(reference_index.context.tdr_root) / "Xml" / "CommonCore"
				for theme_row in _read_all_sheets_path(base_core / "次元配置表.dtxml").get("次元主题表", []):
					theme_id = theme_row.get("搭配ID", "")
					if theme_id in theme_ids:
						theme_rows[theme_id] = theme_row
				for part_row in _read_all_sheets_path(base_core / "次元部件表.dtxml").get("次元部件表", []):
					part_id = part_row.get("部件ID", "")
					if part_id:
						part_rows[part_id] = part_row

				regional_core = reference_index.context.dtxml_path("placeholder.dtxml").parent
				for path in sorted(regional_core.glob("*次元上下架与促销表.dtxml")):
					sheets = _read_all_sheets_path(path)
					for sheet_name, priority, source_kind in (
						("次元部件上下架表", 10, "client"),
						("svr次元部件上下架表", 30, "server"),
					):
						for listing_row in sheets.get(sheet_name, []):
							theme_id = listing_row.get("次元部件或主题ID", "")
							if theme_id in theme_ids and listing_row.get("是否是主题", "") in {"1", "是"}:
								listing_entries[theme_id].append({
									"priority": priority,
									"source_kind": source_kind,
									"file_name": path.name,
									"sheet": sheet_name,
									"row": listing_row,
								})

			gender_labels = {"1": "男", "2": "女"}
			themes = []
			for theme_id in theme_ids:
				theme_row = theme_rows.get(theme_id, {})
				listings = sorted(listing_entries.get(theme_id, []), key=lambda item: int(item["priority"]), reverse=True)
				selected_listing = listings[0] if listings else {}
				listing_row = selected_listing.get("row", {})
				if not isinstance(listing_row, Mapping):
					listing_row = {}
				components = []
				for index in range(1, 11):
					part_id = theme_row.get(f"部件{index}", "")
					if not part_id:
						continue
					part_row = part_rows.get(part_id, {})
					components.append({
						"index": index,
						"part_id": part_id,
						"name": part_row.get("名称", ""),
						"part_type": part_row.get("类型", ""),
						"icon": part_row.get("图标", ""),
						"resolved": bool(part_row),
					})
				themes.append({
					"theme_id": theme_id,
					"gender": gender_labels.get(theme_row.get("性别", ""), theme_row.get("性别", "")),
					"name": listing_row.get("名称") or theme_row.get("名称", ""),
					"description": listing_row.get("描述") or theme_row.get("描述", ""),
					"is_suit": theme_row.get("是否套装", ""),
					"mapped_gender_theme_id": theme_row.get("性转主题ID", ""),
					"release_id": theme_row.get("投放ID", ""),
					"components": components,
					"listed_at": _format_compact_time(str(listing_row.get("上架时间", ""))),
					"delisted_at": _format_compact_time(str(listing_row.get("下架时间", ""))),
					"purchasable": listing_row.get("是否可购买", ""),
					"listing_source_kind": selected_listing.get("source_kind", ""),
				})
			return {
				**base,
				"config_id": ",".join(theme_ids),
				"kind": "dimensional_themes",
				"resolved": bool(themes) and all(theme_id in theme_rows for theme_id in theme_ids),
				"content": {
					"gender_mode": row.get("效果参数1", ""),
					"themes": themes,
				},
				"references": [
					{
						"role": "item_resource_content",
						"direction": "outbound",
						"file_name": "次元配置表.dtxml",
						"sheet": "次元主题表",
						"business_id": theme_id,
						"field": "效果参数2" if index == 0 else "效果参数3",
					}
					for index, theme_id in enumerate(theme_ids)
				],
			}
		if category in {"VALORPASS积分卡", "VP通行证"}:
			season_id = row.get("效果参数2", "")
			season_row: Dict[str, str] = {}
			unlock_row: Dict[str, str] = {}
			season_sheet = "赛季表"
			unlock_sheet = ""
			vp_file = "119.ValorPass系统配置.dtxml"
			if reference_index.context.tdr_root:
				sheets = _read_all_sheets(reference_index.context, vp_file)
				for candidate_sheet in ("svr下发赛季表", "赛季表"):
					candidate = next((item for item in sheets.get(candidate_sheet, []) if item.get("赛季ID") == season_id), {})
					if candidate:
						season_sheet = candidate_sheet
						season_row = candidate
						break
				for candidate_sheet in ("svr下发解锁表", "解锁表"):
					candidate = next((item for item in sheets.get(candidate_sheet, []) if item.get("赛季ID") == season_id), {})
					if candidate:
						unlock_sheet = candidate_sheet
						unlock_row = candidate
						break

			season = {
				"season_id": season_id,
				"start_time": _format_compact_time(season_row.get("赛季开始时间", "")),
				"end_time": _format_compact_time(season_row.get("赛季结束时间", "")),
				"title_cdn": season_row.get("赛季标题CDN", ""),
				"cover_cdn": season_row.get("赛季大厅封面CDN", ""),
				"resolved": bool(season_row),
			}
			season_reference = {
				"role": "item_resource_content",
				"direction": "outbound",
				"file_name": vp_file,
				"sheet": season_sheet,
				"business_id": season_id,
				"field": "效果参数2",
			}
			if category == "VALORPASS积分卡":
				reward_id = row.get("效果参数1", "")
				reward = reference_index.reward(reward_id)
				point_rewards = []
				for leaf in reward.get("leaf_rewards", []):
					if not isinstance(leaf, Mapping) or str(leaf.get("entity_type", "")).upper() != "VALORPASS积分":
						continue
					quantity_min = str(leaf.get("quantity_min", ""))
					quantity_max = str(leaf.get("quantity_max", ""))
					quantity = quantity_min if quantity_min == quantity_max else "-".join(value for value in (quantity_min, quantity_max) if value)
					point_rewards.append({**leaf, "quantity": quantity})
				return {
					**base,
					"config_id": reward_id,
					"kind": "valorpass_points",
					"resolved": bool(season_row) and bool(reward.get("resolved")),
					"content": {
						"season": season,
						"reward_id": reward_id,
						"reward": reward,
						"point_rewards": point_rewards,
					},
					"references": [
						season_reference,
						{
							"role": "gift_content",
							"direction": "outbound",
							"file_name": reward.get("source_file", ""),
							"sheet": "随机奖励配置表",
							"business_id": reward_id,
							"field": "效果参数1",
						},
					],
				}

			pass_code = row.get("效果参数1", "")
			pass_type = {
				"1": "普通通行证（勇者圣典）",
				"2": "精英通行证（精英圣典）",
				"3": "Mini通行证",
			}.get(pass_code, f"未知档位({pass_code})")
			field_prefix = {"1": "普通通行证", "2": "精英通行证", "3": "mini通行证"}.get(pass_code, "")
			return {
				**base,
				"config_id": season_id,
				"kind": "valorpass_unlock",
				"resolved": bool(season_row) and bool(unlock_row),
				"content": {
					"season": season,
					"pass_code": pass_code,
					"pass_type": pass_type,
					"currency": unlock_row.get(f"{field_prefix}货币类型", "") if field_prefix else "",
					"original_price": unlock_row.get(f"{field_prefix}原价", "") if field_prefix else "",
					"discount_price": unlock_row.get(f"{field_prefix}折后价", "") if field_prefix else "",
					"configured_elite_item_id": unlock_row.get("精英通行证道具ID", ""),
					"unlock_source_sheet": unlock_sheet,
				},
				"references": [
					season_reference,
					{
						"role": "item_resource_content",
						"direction": "outbound",
						"file_name": vp_file,
						"sheet": unlock_sheet,
						"business_id": season_id,
						"field": "效果参数1",
					},
				],
			}
		if category == "小应用云积分":
			points_id = row.get("效果参数1", "")
			return {
				**base,
				"config_id": points_id,
				"kind": "mini_app_cloud_points",
				"resolved": bool(points_id),
				"content": {
					"points_id": points_id,
					"unit_amount": "1",
					"usage_resolution": "由奖励、活动和兑换配置中的反向引用确定",
				},
			}
		if category == "限定点券":
			amount = row.get("效果参数1", "")
			batch_file = "【运营配置】限定点券批次表.dtxml"
			batch_sheet = "限定点券批次表"
			batches = []
			for batch_row in _read_sheet(reference_index.context, batch_file, batch_sheet):
				batch_id = batch_row.get("批次ID", "")
				if not batch_id:
					continue
				batches.append({
					"batch_id": batch_id,
					"start_time": _format_compact_time(batch_row.get("开始时间", "")),
					"end_time": _format_compact_time(batch_row.get("结束时间", "")),
				})
			batches.sort(key=lambda batch: int(batch["batch_id"]) if str(batch["batch_id"]).isdigit() else -1)
			latest_batch = batches[-1] if batches else {}
			return {
				**base,
				"config_id": amount,
				"kind": "limited_vouchers",
				"resolved": bool(amount) and bool(batches),
				"content": {
					"amount": amount,
					"batch_binding": "runtime_by_date",
					"batches": batches,
					"latest_configured_batch": latest_batch,
				},
				"reference": {
					"role": "item_resource_content",
					"direction": "outbound",
					"file_name": batch_file,
					"sheet": batch_sheet,
					"business_id": str(latest_batch.get("batch_id", "")),
					"field": "运行时按日期匹配批次",
				},
			}
		if category == "亲密度礼物":
			effect_id = row.get("效果参数1", "")
			gift_type = row.get("效果参数2", "")
			intimacy_points = row.get("效果参数3", "")
			effect_row: Dict[str, str] = {}
			effect_file = "【运营配置】41.道具信息表_Syndra.dtxml"
			effect_sheet = "喇叭信息"
			if effect_id:
				effect_row = next((
					item for item in _read_sheet(reference_index.context, effect_file, effect_sheet)
					if item.get("ID") == effect_id
				), {})
			if not effect_row and reference_index.context.tdr_root and effect_id:
				base_path = Path(reference_index.context.tdr_root) / "Xml" / "CommonCore" / "41.【研发配置】道具信息表_Syndra.dtxml"
				effect_row = next((
					item for item in _read_all_sheets_path(base_path).get(effect_sheet, [])
					if item.get("ID") == effect_id
				), {})
				if effect_row:
					effect_file = base_path.name
			bilateral = any(token in row.get("描述", "") for token in ("双方", "雙方"))
			return {
				**base,
				"config_id": effect_id,
				"kind": "intimacy_gift",
				"resolved": bool(effect_row) and bool(intimacy_points),
				"content": {
					"effect_id": effect_id,
					"gift_type": gift_type,
					"intimacy_points": intimacy_points,
					"recipient_scope": "双方" if bilateral else "接收方或未明确",
					"display_description": effect_row.get("描述", ""),
					"effect_resource": effect_row.get("特效资源路径", ""),
					"background_resource": effect_row.get("背景资源路径", ""),
					"icon_resource": effect_row.get("图标资源路径", ""),
					"minimum_display_seconds": effect_row.get("最小显示时间", ""),
					"maximum_display_seconds": effect_row.get("最大显示时间", ""),
				},
				"reference": {
					"role": "item_resource_content",
					"direction": "outbound",
					"file_name": effect_file,
					"sheet": effect_sheet,
					"business_id": effect_id,
					"field": "效果参数1",
				},
			}
		if category in {"抵价券", "折扣券", "满减抵价券", "满减折扣券"}:
			value = row.get("效果参数1", "")
			target_type = row.get("效果参数2", "").removeprefix("抵扣类型_")
			group_id = row.get("效果参数3", "")
			threshold = row.get("效果参数4", "")
			group_row: Dict[str, str] = {}
			group_file = "【运营配置】41.道具信息表_Syndra.dtxml"
			group_sheet = "英雄皮肤组"
			if group_id:
				group_row = next((
					item for item in _read_sheet(reference_index.context, group_file, group_sheet)
					if item.get("参数ID") == group_id
				), {})
			targets = []
			entity_type = "随机皮肤" if "皮肤" in target_type else "随机英雄" if "英雄" in target_type else ""
			entity_catalog = reference_index._entity_catalog(entity_type) if entity_type else {}
			for index in range(1, 21):
				entity_id = group_row.get(f"参数{index}", "")
				if not entity_id:
					continue
				entity = entity_catalog.get(entity_id, {})
				targets.append({
					"index": index,
					"entity_type": entity_type.removeprefix("随机"),
					"entity_id": entity_id,
					"entity_name": entity.get("name", ""),
					"resolved": bool(entity),
				})
			discount_mode = "fixed_amount" if "抵价券" in category else "percentage"
			return {
				**base,
				"config_id": group_id or value,
				"kind": "purchase_coupon",
				"resolved": bool(value) and (not group_id or bool(group_row)),
				"content": {
					"coupon_type": category,
					"discount_mode": discount_mode,
					"value": value,
					"target_type": target_type,
					"target_group_id": group_id,
					"targets": targets,
					"threshold_parameter": threshold,
					"limited_hours": row.get("限时道具有效期", ""),
					"usable_start_time": _format_compact_time(row.get("可使用开始日期", "")),
					"usable_end_time": _format_compact_time(row.get("可使用结束日期", "")),
				},
				**({
					"reference": {
						"role": "item_resource_content",
						"direction": "outbound",
						"file_name": group_file,
						"sheet": group_sheet,
						"business_id": group_id,
						"field": "效果参数3",
					},
				} if group_id else {}),
			}
		if category == "预选礼包" and config_id:
			file_name = "预选择配置.dtxml"
			config_sheet = "预选择"
			item_sheet = "预选择物品"
			config_row = next((
				item for item in _read_sheet(reference_index.context, file_name, config_sheet)
				if item.get("ID") == config_id
			), {})
			selection_items = {
				item.get("ID", ""): item
				for item in _read_sheet(reference_index.context, file_name, item_sheet)
				if item.get("ID")
			}
			entity_type_map = {
				"英雄": "随机英雄",
				"英雄皮肤": "随机皮肤",
				"头像框": "随机头像框",
				"局内动作": "随机局内动作",
			}
			options = []
			for index in range(1, 151):
				option_type = config_row.get(f"选项{index}类型", "")
				option_config_id = config_row.get(f"选项{index}ID", "")
				if not any((option_type, option_config_id)):
					continue
				selection_row = selection_items.get(option_config_id, {})
				entity_type = selection_row.get("物品类型", "")
				entity_id = selection_row.get("物品ID", "")
				quantity = selection_row.get("物品数量", "")
				entity: Mapping[str, str] = {}
				if entity_type == "道具":
					item_row = reference_index.item_catalog.rows.get(entity_id, {})
					if item_row:
						entity = {
							"name": item_row.get("名称", ""),
							"source_file": reference_index.item_catalog.sources.get(entity_id, ""),
							"sheet": reference_index.item_catalog.source_sheets.get(entity_id, ""),
						}
				elif entity_type in entity_type_map:
					entity = reference_index._entity_catalog(entity_type_map[entity_type]).get(entity_id, {})
				options.append({
					"index": index,
					"display_order": config_row.get(f"选项{index}展示排序", ""),
					"option_type": option_type,
					"option_config_id": option_config_id,
					"entity_type": entity_type,
					"entity_id": entity_id,
					"entity_name": entity.get("name", ""),
					"quantity": quantity,
					"resolved": bool(selection_row) and bool(entity),
					"source_file": entity.get("source_file", ""),
					"source_sheet": entity.get("sheet", ""),
				})
			return {
				**base,
				"kind": "preselection_gift",
				"resolved": bool(config_row) and bool(options) and all(option["resolved"] for option in options),
				"content": {
					"selection_config_id": config_id,
					"selection_mode_code": row.get("效果参数2", ""),
					"option_count": len(options),
					"resolved_option_count": sum(bool(option["resolved"]) for option in options),
					"options": options,
				},
				"references": [
					{
						"role": "preselection_config",
						"direction": "outbound",
						"file_name": file_name,
						"sheet": config_sheet,
						"business_id": config_id,
						"field": "效果参数1",
					},
					{
						"role": "preselection_config",
						"direction": "outbound",
						"file_name": file_name,
						"sheet": item_sheet,
						"business_id": ",".join(option["option_config_id"] for option in options),
						"field": "选项NID",
					},
				],
			}
		resource_specs = {
			"头像道具": (
				("【运营配置】玩家头像信息表*.dtxml", "玩家头像信息", "头像ID", ("头像名称", "头像描述"), "client", 10),
				("玩家头像信息表svr下发*.dtxml", "玩家头像信息", "头像ID", ("头像名称", "头像描述"), "server", 30),
			),
			"头像框资源": (
				("【运营配置】头像框信息表*.dtxml", "头像框信息表", "头像框ID", ("头像框描述",), "client", 10),
				("头像框信息表增量下发*.dtxml", "头像框信息表", "头像框ID", ("头像框描述",), "server_increment", 30),
			),
		}
		if category in resource_specs and config_id:
			definitions = []
			if reference_index.context.tdr_root:
				common_core = reference_index.context.dtxml_path("placeholder.dtxml").parent
				for pattern, sheet_name, id_field, name_fields, source_kind, priority in resource_specs[category]:
					for path in sorted(common_core.glob(pattern)):
						resource_row = next((
							item for item in _read_sheet(reference_index.context, path.name, sheet_name)
							if item.get(id_field) == config_id
						), {})
						if resource_row:
							definitions.append({
								"priority": priority,
								"source_kind": source_kind,
								"file_name": path.name,
								"sheet": sheet_name,
								"row": resource_row,
								"name": next((resource_row.get(field, "") for field in name_fields if resource_row.get(field)), ""),
							})
			selected = max(definitions, key=lambda item: int(item["priority"])) if definitions else {}
			resource_row = selected.get("row", {}) if isinstance(selected.get("row"), Mapping) else {}
			return {
				**base,
				"kind": "resource_unlock",
				"resolved": bool(selected),
				"content": {
					"resource_type": category.removesuffix("道具").removesuffix("资源"),
					"resource_id": config_id,
					"resource_name": selected.get("name", ""),
					"source_kind": selected.get("source_kind", ""),
					"icon": resource_row.get("头像图标") or resource_row.get("头像框图标", ""),
					"effect": resource_row.get("特效名") or resource_row.get("特效", ""),
					"display_start_time": _format_compact_time(resource_row.get("显示开始时间", "")),
					"available_sources": [
						{
							"source_kind": item["source_kind"],
							"file_name": item["file_name"],
							"sheet": item["sheet"],
							"name": item["name"],
						}
						for item in definitions
					],
				},
				"reference": {
					"role": "item_resource_content",
					"direction": "outbound",
					"file_name": selected.get("file_name", ""),
					"sheet": selected.get("sheet", ""),
					"business_id": config_id,
					"field": "效果参数1",
				},
			}
		return {**base, "kind": "category_only", "resolved": bool(category)}

	@staticmethod
	def _category_display_lines(category_usage: Mapping[str, object]) -> List[str]:
		kind = category_usage.get("kind")
		content = category_usage.get("content")
		if not isinstance(content, Mapping):
			return []
		if kind == "random_reward_gift":
			labels = _reward_leaf_labels(content)
			return [
				f"礼包配置: {category_usage.get('config_id', '')}",
				f"礼包内容: {', '.join(labels) if labels else '未找到奖励内容'}",
			]
		if kind == "activity_token":
			def activity_labels(activities: object, limit: int = 6) -> List[str]:
				if not isinstance(activities, Sequence) or isinstance(activities, (str, bytes)):
					return []
				labels = []
				for activity in activities[:limit]:
					if not isinstance(activity, Mapping):
						continue
					identity = " ".join(value for value in (
						str(activity.get("activity_type", "")),
						str(activity.get("activity_id", "")),
						str(activity.get("activity_name", "")),
					) if value)
					if activity.get("activity_index"):
						identity += f"（索引 {activity.get('activity_index')}）"
					labels.append(identity)
				remaining = len(activities) - len(labels)
				if remaining > 0:
					labels.append(f"另有 {remaining} 项")
				return labels

			acquisition_labels = activity_labels(content.get("acquisition_activities", []))
			consumption_labels = activity_labels(content.get("consumption_activities", []))
			related_labels = activity_labels(content.get("related_activities", []))
			mode_labels = {
				"progress_counter": "累计进度型",
				"exchange_currency": "兑换货币型",
				"hybrid": "累计进度 + 兑换混合型",
				"acquisition_only": "仅找到产出，用途待关联",
				"unresolved": "用途未解析",
			}
			lines = [
				f"活动 Token: {content.get('token_id', '')} {content.get('token_name', '')}",
				f"业务模式: {mode_labels.get(str(content.get('business_mode', '')), content.get('business_mode', ''))}",
				f"获取活动: {', '.join(acquisition_labels) if acquisition_labels else '未找到活动引用'}",
			]
			for activity in content.get("progress_activities", []):
				if not isinstance(activity, Mapping):
					continue
				lines.append(
					f"进度活动: {activity.get('activity_type', '')} {activity.get('activity_id', '')} {activity.get('activity_name', '')}"
				)
				stage_labels = []
				for stage in activity.get("stages", []):
					if not isinstance(stage, Mapping):
						continue
					reward = stage.get("reward", {})
					reward_labels = _reward_leaf_labels(reward) if isinstance(reward, Mapping) else []
					stage_labels.append(
						f"{stage.get('target_value', '')} → {', '.join(reward_labels) if reward_labels else '未找到奖励'}"
					)
				lines.append(f"进度档位: {'; '.join(stage_labels) if stage_labels else '未找到档位'}")
			if consumption_labels:
				lines.append(f"兑换消耗: {', '.join(consumption_labels)}")
			elif content.get("business_mode") == "progress_counter":
				lines.append("兑换消耗: 无，当前为累计持有数量计算进度")
			else:
				lines.append("兑换消耗: 未找到活动引用")
			if related_labels:
				lines.append(f"归属活动: {', '.join(related_labels)}")
			return lines
		if kind == "deferred_category":
			return [f"业务解析: {content.get('category', '')} 已预留，当前版本暂不展开"]
		if kind == "trial_card":
			lines = [
				f"体验卡: {content.get('target_type', '')} {content.get('target_id', '')} {content.get('target_name', '')} | {content.get('duration_label', '')}",
			]
			if content.get("owned_compensation_diamonds"):
				lines.append(f"已拥有补偿: {content.get('owned_compensation_diamonds', '')} 钻石")
			conversion = content.get("auto_conversion", {})
			if isinstance(conversion, Mapping) and conversion.get("item_id"):
				lines.append(
					f"自动转换: 道具 {conversion.get('item_id', '')} {conversion.get('item_name', '')} ×{conversion.get('quantity', '')}"
				)
			return lines
		if kind == "treasure_draw_ticket":
			mode_labels = {
				"multi_system": "常驻夺宝 + 活动抽奖",
				"standard_treasure": "常驻夺宝",
				"activity_draw": "活动抽奖",
				"inactive_or_unresolved": "未找到启用用途",
			}
			lines = [
				f"夺宝抽奖券: {content.get('ticket_id', '')} {content.get('ticket_name', '')}",
				f"业务模式: {mode_labels.get(str(content.get('business_mode', '')), content.get('business_mode', ''))}",
			]
			for draw in content.get("standard_draws", []):
				if not isinstance(draw, Mapping):
					continue
				option_labels = [
					f"{option.get('draw_type', '')}×{option.get('cost_quantity', '')}券"
					for option in draw.get("draw_options", []) if isinstance(option, Mapping)
				]
				lines.append(
					f"常驻夺宝: {draw.get('draw_label', '')}（配置 {draw.get('draw_id', '')}） | {', '.join(option_labels)} | 稀有保底 {draw.get('rare_min_draws', '')}-{draw.get('rare_max_draws', '')} 抽"
				)
				latest_pool = draw.get("latest_pool", {})
				if not isinstance(latest_pool, Mapping) or not latest_pool:
					continue
				prize_labels = []
				for reward in latest_pool.get("rewards", []):
					if not isinstance(reward, Mapping) or str(reward.get("prize_grade", "")) not in {"2", "3"}:
						continue
					identity = " ".join(value for value in (
						str(reward.get("entity_type", "")),
						str(reward.get("entity_id", "")),
						str(reward.get("entity_name", "")),
					) if value)
					prize_labels.append(f"{identity} ×{reward.get('quantity', '')}（{reward.get('probability_per_10000', '')}/10000）")
				lines.append(
					f"最新奖池: {latest_pool.get('pool_id', '')} | {latest_pool.get('reward_count', 0)} 项 | 概率合计 {latest_pool.get('total_probability_per_10000', 0)}/10000"
				)
				lines.append(f"稀有内容: {', '.join(prize_labels) if prize_labels else '未配置'}")
			for draw in content.get("activity_draws", []):
				if not isinstance(draw, Mapping):
					continue
				lines.append(
					f"活动抽奖: {draw.get('draw_id', '')} {draw.get('activity_name', '')} | 奖池 {draw.get('pool_id', '')} | 单次消耗 {draw.get('cost_quantity', '')} 券"
				)
			return lines
		if kind == "loudspeaker":
			return [
				f"喇叭道具: {content.get('loudspeaker_type', '')}（配置 {content.get('config_id', '')}）",
				f"展示范围: {content.get('display_scope', '')} | 最多 {content.get('character_limit', '')} 字",
				f"显示时长: {content.get('minimum_display_seconds', '')}-{content.get('maximum_display_seconds', '')} 秒",
			]
		if kind == "rank_protection_card":
			validity = "未配置"
			if content.get("validity_hours"):
				validity = f"{content.get('validity_hours', '')} 小时"
				if content.get("validity_days"):
					validity += f"（{content.get('validity_days', '')} 天）"
			return [
				f"排位守护卡: {content.get('effect_type', '')}",
				f"效果参数2: {content.get('effect_parameter_2_code', '') or '未配置'}（原始代码，含义待确认）",
				f"道具有效期: {validity}",
				f"可使用时间: {content.get('available_start_time', '') or '未配置'} 至 {content.get('available_end_time', '') or '未配置'}",
			]
		if kind == "system_voice":
			preview_labels = [
				f"{preview.get('title', '')} [{preview.get('event', '')}]"
				for preview in content.get("previews", []) if isinstance(preview, Mapping)
			]
			return [
				f"系统语音: {content.get('voice_id', '')} {content.get('title', '')}",
				f"配音: {content.get('cv', '') or '未配置'} | {content.get('subtitle', '')}",
				f"资源: DLC={content.get('dlc_type', '')} | Bank={content.get('bank_resource', '')}",
				f"配置时间: {content.get('start_time', '') or '未配置'} 至 {content.get('end_time', '') or '未配置'} | 关闭标记={content.get('closed_code', '') or '未配置'}",
				f"生效配置: {content.get('source_kind', '')} / {content.get('source_sheet', '')}",
				f"试听: {'; '.join(preview_labels) if preview_labels else '未配置'}",
			]
		if kind == "delay_draw_gift":
			choices = content.get("choices", [])
			labels = [
				" ".join(value for value in (
					str(choice.get("type", "")), str(choice.get("id", "")), str(choice.get("name", "")),
				) if value) + (f" ×{choice.get('quantity')}" if choice.get("quantity") else "")
				for choice in choices if isinstance(choice, Mapping)
			]
			return [
				f"延后领用配置: {category_usage.get('config_id', '')} | 可选 {content.get('select_count', '')} 个",
				f"候选奖励: {', '.join(labels) if labels else '未找到配置'}",
			]
		if kind == "activity_draw_gift":
			guarantee_labels = []
			for pool in content.get("pools", []):
				if not isinstance(pool, Mapping) or not str(pool.get("role", "")).startswith("guarantee_"):
					continue
				guarantee_labels.append(
					f"{pool.get('required_draws', '')}抽->{pool.get('pool_id', '')}"
					+ ("(循环)" if str(pool.get("repeatable", "")) in {"1", "是"} else "")
				)
			return [
				f"活动抽奖批次: {content.get('batch_id', '')} | 规则={content.get('rule_id', '')}",
				f"奖池概况: {content.get('pool_count', 0)} 个奖池，{content.get('reward_group_count', 0)} 组奖励，展开后 {content.get('final_reward_count', 0)} 项最终内容",
				f"保底节点: {', '.join(guarantee_labels) if guarantee_labels else '未配置'}",
			]
		if kind == "quick_message":
			return [
				f"快捷消息: {content.get('message_id', '')} {content.get('text', '')}",
				f"消息主题: {content.get('theme_id', '')} {content.get('theme_name', '')}",
				f"主题时间: {' 至 '.join(value for value in (str(content.get('theme_start_time', '')), str(content.get('theme_end_time', ''))) if value)}",
			]
		if kind == "battle_effect":
			listing_time = " 至 ".join(
				value for value in (
					str(content.get("listed_at", "")),
					str(content.get("delisted_at", "")),
				) if value
			)
			return [
				f"单局特效: {content.get('effect_id', '')} {content.get('effect_name', '')}",
				f"特效类型: {content.get('effect_type', '')} | 有效时长: {content.get('duration_label', '')}",
				f"上架信息: {listing_time or '未配置时间'} | 可购买={content.get('purchasable', '')}",
			]
		if kind == "dimensional_parts":
			part_lines = []
			for part in content.get("parts", []):
				if not isinstance(part, Mapping):
					continue
				part_lines.append(
					f"次元部件({part.get('gender', '')}): {part.get('part_id', '')} "
					f"{part.get('name', '')} | {part.get('part_type', '')} | 投放ID={part.get('release_id', '')}"
				)
			return part_lines
		if kind == "dimensional_themes":
			theme_lines = []
			for theme in content.get("themes", []):
				if not isinstance(theme, Mapping):
					continue
				component_labels = [
					" ".join(value for value in (
						str(component.get("part_id", "")), str(component.get("name", "")),
					) if value)
					for component in theme.get("components", []) if isinstance(component, Mapping)
				]
				theme_lines.append(
					f"次元主题({theme.get('gender', '')}): {theme.get('theme_id', '')} "
					f"{theme.get('name', '')} | 投放ID={theme.get('release_id', '')}"
				)
				theme_lines.append(f"主题部件: {', '.join(component_labels) if component_labels else '未配置'}")
			return theme_lines
		if kind == "valorpass_points":
			season = content.get("season", {})
			if not isinstance(season, Mapping):
				season = {}
			points = [
				str(reward.get("quantity", ""))
				for reward in content.get("point_rewards", [])
				if isinstance(reward, Mapping) and reward.get("quantity")
			]
			return [
				f"VP赛季: 第{season.get('season_id', '')}篇章 | {season.get('start_time', '')} 至 {season.get('end_time', '')}",
				f"增加积分: {', '.join(points) if points else '未解析'} | 奖励ID={content.get('reward_id', '')}",
			]
		if kind == "valorpass_unlock":
			season = content.get("season", {})
			if not isinstance(season, Mapping):
				season = {}
			return [
				f"VP赛季: 第{season.get('season_id', '')}篇章 | {season.get('start_time', '')} 至 {season.get('end_time', '')}",
				f"通行证档位: {content.get('pass_type', '')}",
				f"价格配置: {content.get('currency', '')} 原价={content.get('original_price', '')} 折后价={content.get('discount_price', '')}",
			]
		if kind == "mini_app_cloud_points":
			return [
				f"小应用云积分: 货币ID={content.get('points_id', '')} | 每个道具增加 {content.get('unit_amount', '')}",
				f"用途识别: {content.get('usage_resolution', '')}",
			]
		if kind == "limited_vouchers":
			latest_batch = content.get("latest_configured_batch", {})
			if not isinstance(latest_batch, Mapping):
				latest_batch = {}
			return [
				f"限定点券: {content.get('amount', '')}",
				"批次绑定: 道具未固定批次，使用时按限定点券批次表和日期匹配",
				f"最新配置批次: {latest_batch.get('batch_id', '')} | {latest_batch.get('start_time', '')} 至 {latest_batch.get('end_time', '')}",
			]
		if kind == "intimacy_gift":
			return [
				f"亲密度礼物: {content.get('gift_type', '')} | {content.get('recipient_scope', '')} +{content.get('intimacy_points', '')} 点",
				f"展示效果: {content.get('effect_id', '')} {content.get('display_description', '')}",
				f"显示时长: {content.get('minimum_display_seconds', '')}-{content.get('maximum_display_seconds', '')} 秒",
			]
		if kind == "purchase_coupon":
			if content.get("discount_mode") == "fixed_amount":
				discount_label = f"抵扣 {content.get('value', '')} 点券"
			else:
				value = str(content.get("value", ""))
				discount_label = f"支付原价 {value}%" + (f"（{int(value) / 10:g}折）" if value.isdigit() else "")
			target_labels = [
				" ".join(value for value in (
					str(target.get("entity_id", "")), str(target.get("entity_name", "")),
				) if value)
				for target in content.get("targets", []) if isinstance(target, Mapping)
			]
			lines = [
				f"优惠券: {content.get('coupon_type', '')} | {discount_label}",
				f"适用范围: {content.get('target_type', '')}",
			]
			if content.get("threshold_parameter"):
				lines.append(f"价格条件参数: {content.get('threshold_parameter', '')}")
			if content.get("target_group_id"):
				lines.append(
					f"指定对象组: {content.get('target_group_id', '')} | "
					f"{', '.join(target_labels) if target_labels else '未解析到对象'}"
				)
			return lines
		if kind == "preselection_gift":
			option_labels = []
			for option in content.get("options", [])[:8]:
				if not isinstance(option, Mapping):
					continue
				identity = " ".join(value for value in (
					str(option.get("entity_type", "")),
					str(option.get("entity_id", "")),
					str(option.get("entity_name", "")),
				) if value)
				quantity = str(option.get("quantity", ""))
				option_labels.append(identity + (f" ×{quantity}" if quantity else ""))
			option_count = int(content.get("option_count", 0) or 0)
			remaining = max(option_count - len(option_labels), 0)
			if remaining:
				option_labels.append(f"另有 {remaining} 项")
			mode_code = content.get("selection_mode_code") or "未配置"
			return [
				f"预选礼包: 配置 {content.get('selection_config_id', '')} | {option_count} 个候选 | 选择模式代码={mode_code}",
				f"候选内容: {', '.join(option_labels) if option_labels else '未找到配置'}",
			]
		if kind == "resource_unlock":
			return [
				f"解锁资源: {content.get('resource_type', '')} {content.get('resource_id', '')} {content.get('resource_name', '')}",
				f"资源来源: {content.get('source_kind', '')}",
			]
		return []

	@staticmethod
	def _validity_checks(row: Mapping[str, str], references: Sequence[Mapping[str, object]]) -> List[Dict[str, object]]:
		limited_hours_text = str(row.get("限时道具有效期", "")).strip()
		try:
			limited_hours = float(limited_hours_text) if limited_hours_text else None
		except ValueError:
			limited_hours = None
		item_start = _parse_compact_time(row.get("可使用开始日期"))
		item_end = _parse_compact_time(row.get("可使用结束日期"))
		checks = []
		seen_activities = set()
		for reference in references:
			if reference.get("file_name") != "日常活动表.dtxml":
				continue
			activity_id = str(reference.get("business_id", ""))
			activity_start_raw = str(reference.get("activity_start_time", ""))
			activity_end_raw = str(reference.get("activity_end_time", ""))
			key = (str(reference.get("sheet", "")), activity_id, activity_start_raw, activity_end_raw)
			if not activity_id or key in seen_activities:
				continue
			seen_activities.add(key)
			activity_start = _parse_compact_time(activity_start_raw)
			activity_end = _parse_compact_time(activity_end_raw)
			base = {
				"activity_id": activity_id,
				"activity_name": str(reference.get("business_name", "")),
				"activity_sheet": str(reference.get("sheet", "")),
				"activity_start_time": _format_compact_time(activity_start_raw),
				"activity_end_time": _format_compact_time(activity_end_raw),
			}
			if not activity_start or not activity_end:
				checks.append({**base, "status": "unknown", "message": "活动时间不完整，无法比较道具有效期"})
				continue

			problems = []
			if item_start and item_start > activity_start:
				problems.append("道具可使用开始时间晚于活动开始时间")
			if item_end and item_end < activity_end:
				problems.append("道具可使用结束时间早于活动结束时间")
			duration_hours = ceil((activity_end - activity_start).total_seconds() / 3600)
			if limited_hours is not None and limited_hours < duration_hours:
				problems.append(f"道具有效期 {limited_hours:g} 小时短于活动持续 {duration_hours} 小时")
			if not any((item_start, item_end, limited_hours is not None)):
				status = "not_configured"
				message = "道具未配置有效期限制"
			elif problems:
				status = "warning"
				message = "；".join(problems)
			else:
				status = "passed"
				message = "道具有效期覆盖活动时间"
			checks.append({
				**base,
				"status": status,
				"message": message,
				"activity_duration_hours": duration_hours,
			})
		return checks

	def analyze(self, changes: Sequence[Mapping[str, object]], context: ModuleContext) -> Dict[str, object]:
		items = []
		reference_index = ActivityReferenceIndex(context)
		changes_by_item: DefaultDict[str, List[Mapping[str, object]]] = defaultdict(list)
		for change in changes:
			item_id = _row(change).get("ID") or _business_key_value(change, "ID")
			if not item_id:
				item_id = _business_key(change).removeprefix("ID=")
			changes_by_item[item_id].append(change)

		module_warnings = []
		for item_id, item_changes in changes_by_item.items():
			fallback_row = next((_row(change) for change in reversed(item_changes) if _row(change)), {})
			row = reference_index.item_catalog.rows.get(item_id, fallback_row)
			source_resolution = reference_index.item_catalog.resolution(item_id)
			name = row.get("名称", "")
			category = row.get("类型", "")
			hidden_item = self._hidden_item_state(row)
			category_usage = self._category_usage(row, reference_index)
			references = self._references(item_id, item_changes, reference_index, category_usage)
			usage_roles = list(dict.fromkeys(
				self.REFERENCE_ROLE_LABELS.get(str(reference.get("role", "")), "")
				for reference in references
				if self.REFERENCE_ROLE_LABELS.get(str(reference.get("role", "")), "")
			))
			purpose = self.CATEGORY_PURPOSES.get(category, "该类别尚未配置专用解读")
			if usage_roles:
				purpose = f"{purpose}；当前引用显示：{'、'.join(usage_roles)}"
			validity_checks = self._validity_checks(row, references)
			warning_count = sum(check.get("status") == "warning" for check in validity_checks)
			change_types = list(dict.fromkeys(str(change.get("change_type", "")) for change in item_changes))
			display_lines = [
				f"道具: {' '.join(value for value in (item_id, name) if value)}",
				f"类别: {category}",
				(
					f"隐藏道具: 是（原始值={hidden_item['raw_value']}）"
					if hidden_item["is_hidden"] else
					f"隐藏道具: 未识别配置值（原始值={hidden_item['raw_value']}）"
					if hidden_item["status"] == "unknown" else
					"隐藏道具: 否"
				),
				f"生效来源: {source_resolution['selected_source_kind']} / {source_resolution['selected_sheet']}",
				f"用途: {purpose}",
				f"描述: {row.get('描述', '')}",
				f"引用位置: {len(references)} 处（已识别业务关系）",
				f"有效期检查: {len(validity_checks)} 个活动，{warning_count} 个风险",
				f"本次变化: {len(item_changes)} 条（{', '.join(change_types)}）",
			]
			display_lines.extend(self._category_display_lines(category_usage))
			if source_resolution["category_conflict"]:
				conflict_message = (
					f"类别冲突: {' / '.join(source_resolution['categories'])}；"
					f"按优先级采用 {category or '未配置'}"
				)
				display_lines.append(conflict_message)
				module_warnings.append({
					"type": "item_category_conflict",
					"item_id": item_id,
					"message": conflict_message,
					"source_resolution": source_resolution,
				})
			for reference in references:
				display_lines.append(
					f"- {reference.get('sheet', '')} {reference.get('business_id', '')}"
					f" {reference.get('business_name', '')} / {reference.get('field', '')}"
					f"（{self.REFERENCE_ROLE_LABELS.get(str(reference.get('role', '')), str(reference.get('role', ''))) }）"
				)
			for check in validity_checks:
				display_lines.append(
					f"- 有效期[{check['status']}]: {check['activity_sheet']} {check['activity_id']}"
					f" {check['message']}"
				)
			items.append({
				"object_type": "item",
				"object_id": item_id,
				"name": name,
				"summary": f"道具 {item_id}{f'（{name}）' if name else ''}配置发生变化",
				"display_lines": display_lines,
				"display_text": "\n".join(display_lines),
				"changes": [
					{
						**_change_reference(change),
						"field_changes": _field_change_details(change),
					}
					for change in item_changes
				],
				"category": category,
				"hidden_item": hidden_item,
				"source_resolution": source_resolution,
				"purpose": purpose,
				"category_usage": category_usage,
				"usage_roles": usage_roles,
				"references": references,
				"reference_scope": "recognized_business_relations",
				"validity": {
					"limited_hours": limited_hours_text if (limited_hours_text := row.get("限时道具有效期", "")) else "",
					"usable_start_time": _format_compact_time(row.get("可使用开始日期", "")),
					"usable_end_time": _format_compact_time(row.get("可使用结束日期", "")),
					"checks": validity_checks,
					"warning_count": warning_count,
				},
				"current_state": _selected_fields(
					row,
					("ID", "名称", "类型", "分类", "描述", "图标", "效果", "参数", "有效期", "可使用", "活动"),
				),
			})
		return {
			"module": self.id,
			"name": self.name,
			"status": "interpreted",
			"matched_change_count": len(changes),
			"item_count": len(items),
			"hidden_item_count": sum(bool(item["hidden_item"]["is_hidden"]) for item in items),
			"items": items,
			"warnings": module_warnings,
		}


def _collect_unresolved_references(value: object) -> List[Dict[str, object]]:
	results = []
	if isinstance(value, Mapping):
		unresolved = value.get("unresolved_references")
		if isinstance(unresolved, list):
			results.extend(item for item in unresolved if isinstance(item, dict))
		for key, item in value.items():
			if key != "unresolved_references":
				results.extend(_collect_unresolved_references(item))
	elif isinstance(value, list):
		for item in value:
			results.extend(_collect_unresolved_references(item))
	return results


def _module_overview(
	results: Sequence[Mapping[str, object]],
	failures: Sequence[Mapping[str, object]],
	unmatched: Sequence[Mapping[str, object]],
	deferred: Sequence[Mapping[str, object]],
) -> Dict[str, object]:
	direct_counts: DefaultDict[str, int] = defaultdict(int)
	shallow_counts: DefaultDict[str, int] = defaultdict(int)
	other_config_ids = set()
	related_ids = set()
	hidden_items = []
	limited_reward_count = 0
	limited_slot_count = 0
	structural_risks = []
	for module in results:
		if module.get("module") == "output_limit":
			limited_reward_count += int(module.get("item_count", 0) or 0)
			limited_slot_count += int(module.get("limited_slot_count", 0) or 0)
		if module.get("module") == "item":
			for item in module.get("items", []):
				if not isinstance(item, Mapping):
					continue
				hidden_state = item.get("hidden_item")
				if isinstance(hidden_state, Mapping) and hidden_state.get("is_hidden"):
					hidden_items.append({
						"item_id": str(item.get("object_id", "")),
						"item_name": str(item.get("name", "")),
					})
		if module.get("module") != "activity":
			continue
		for item in module.get("items", []):
			if not isinstance(item, Mapping):
				continue
			activity_type = str(item.get("activity_type", "未识别活动"))
			if item.get("changes"):
				if activity_type in ACTIVITY_TYPE_LABELS:
					direct_counts[activity_type] += 1
					content = item.get("activity_content")
					if isinstance(content, Mapping) and content.get("kind") == "not_implemented":
						shallow_counts[activity_type] += 1
				else:
					other_config_ids.add((activity_type, str(item.get("object_id", ""))))
			else:
				related_ids.add(str(item.get("object_id", "")))
			structural_risks.extend(_collect_unresolved_references(item.get("activity_content")))
	for failure in failures:
		structural_risks.append({
			"type": "module_failure",
			"id": str(failure.get("module", "")),
			"path": "module_analysis",
			"message": str(failure.get("message", "")),
		})
	unique_risks = []
	seen_risks = set()
	for risk in structural_risks:
		key = json.dumps(risk, ensure_ascii=False, sort_keys=True, default=str)
		if key not in seen_risks:
			seen_risks.add(key)
			unique_risks.append(risk)
	updates = [
		{
			"activity_type": activity_type,
			"label": ACTIVITY_TYPE_LABELS[activity_type],
			"count": count,
			"detail_status": "diff_only" if shallow_counts[activity_type] else "interpreted",
		}
		for activity_type, count in sorted(direct_counts.items())
	]
	content_updates = [
		{
			"content_type": "activity",
			"module": "activity",
			"label": item["label"],
			"count": item["count"],
			"detail_status": item["detail_status"],
		}
		for item in updates
	]
	module_labels = {
		"skin": "皮肤",
		"reward": "随机奖励",
		"output_limit": "限量奖励组",
		"item": "道具",
	}
	for module in results:
		module_id = str(module.get("module", ""))
		if module_id not in module_labels:
			continue
		count = int(module.get("item_count", 0) or 0)
		if count:
			content_updates.append({
				"content_type": module_id,
				"module": module_id,
				"label": module_labels[module_id],
				"count": count,
				"detail_status": "interpreted",
			})
	update_text = "、".join(
		f"{item['label']} {item['count']}个" for item in content_updates
	) or "未识别到业务内容更新"
	lines = [
		f"本次更新: {update_text}",
		f"关联影响: {len(related_ids)}个历史活动",
		(
			f"结构风险: {len(unique_risks)}项"
			if unique_risks else "结构风险: 当前未发现"
		),
		"业务规则: 暂未启用",
	]
	if hidden_items:
		hidden_labels = [
			" ".join(value for value in (item["item_id"], item["item_name"]) if value)
			for item in hidden_items[:5]
		]
		remaining = len(hidden_items) - len(hidden_labels)
		if remaining:
			hidden_labels.append(f"另有{remaining}个")
		lines.insert(2, f"隐藏道具: {len(hidden_items)}个（{'、'.join(hidden_labels)}）")
	if limited_reward_count:
		lines.insert(2, f"限量产出: {limited_reward_count}组随机奖励，{limited_slot_count}个受限奖励槽位")
	shallow_text = "、".join(
		f"{ACTIVITY_TYPE_LABELS[activity_type]} {count}个"
		for activity_type, count in sorted(shallow_counts.items())
		if count
	)
	if shallow_text:
		lines.append(f"仅差异展示: {shallow_text}")
	if other_config_ids:
		lines.append(f"其他活动配置: {len(other_config_ids)}项")
	if unmatched or deferred:
		lines.append(f"未业务解读: {len(unmatched) + len(deferred)}条变更")
	return {
		"activity_updates": updates,
		"content_updates": content_updates,
		"direct_content_count": sum(int(item["count"]) for item in content_updates),
		"direct_activity_count": sum(direct_counts.values()),
		"related_activity_count": len(related_ids),
		"diff_only_activity_count": sum(shallow_counts.values()),
		"other_activity_config_count": len(other_config_ids),
		"hidden_item_count": len(hidden_items),
		"hidden_items": hidden_items,
		"limited_reward_count": limited_reward_count,
		"limited_slot_count": limited_slot_count,
		"has_structural_risk": bool(unique_risks),
		"structural_risk_count": len(unique_risks),
		"structural_risks": unique_risks,
		"business_rule_status": "not_enabled",
		"display_lines": lines,
		"display_text": "\n".join(lines),
	}


class ModuleRegistry:
	def __init__(self, modules: Optional[Sequence[ChangeSetModule]] = None) -> None:
		self.modules = list(modules or [SkinModule(), ActivityModule(), RewardModule(), OutputLimitModule(), ItemModule()])

	def analyze(self, changeset: MutableMapping[str, object], context: ModuleContext) -> Dict[str, object]:
		analysis_started = time.perf_counter()
		changes = [change for change in changeset.get("changes", []) if isinstance(change, MutableMapping)]
		matched: Dict[str, List[MutableMapping[str, object]]] = {module.id: [] for module in self.modules}
		unmatched: List[Dict[str, object]] = []
		deferred: List[Dict[str, object]] = []
		for change in changes:
			semantic = change.get("semantic_analysis")
			if isinstance(semantic, Mapping) and semantic.get("status") == "deferred":
				deferred.append(_change_reference(change))
				continue
			module = next((candidate for candidate in self.modules if candidate.matches(change)), None)
			if module is None:
				change["semantic_analysis"] = {"status": "module_not_found"}
				unmatched.append(_change_reference(change))
				continue
			change["semantic_analysis"] = {"status": "interpreted", "module": module.id}
			matched[module.id].append(change)

		results = []
		failures = []
		module_durations: Dict[str, float] = {}
		for module in self.modules:
			module_changes = matched[module.id]
			impact_matcher = getattr(module, "impact_matches", None)
			impact_changes = [
				change for change in changes
				if callable(impact_matcher) and impact_matcher(change) and change not in module_changes
			]
			analysis_changes = [*module_changes, *impact_changes]
			if not analysis_changes:
				continue
			try:
				module_started = time.perf_counter()
				result = module.analyze(analysis_changes, context)
				duration = time.perf_counter() - module_started
				module_durations[module.id] = duration
				result["duration_seconds"] = round(duration, 3)
				if result.get("item_count", 0):
					results.append(result)
			except Exception as error:
				failures.append({"module": module.id, "message": str(error)})
				for change in module_changes:
					change["semantic_analysis"] = {
						"status": "module_failed",
						"module": module.id,
					}

		interpreted_count = sum(len(items) for items in matched.values()) - sum(
			len(matched.get(str(item.get("module", "")), [])) for item in failures
		)
		status = "passed"
		if failures:
			status = "warning"
		elif unmatched or deferred:
			status = "partial"
		overview = _module_overview(results, failures, unmatched, deferred)
		total_duration = time.perf_counter() - analysis_started
		return {
			"schema_version": MODULE_ANALYSIS_SCHEMA_VERSION,
			"status": status,
			"overview": overview,
			"summary": {
				"change_count": len(changes),
				"interpreted_change_count": interpreted_count,
				"module_not_found_count": len(unmatched),
				"deferred_change_count": len(deferred),
				"module_failed_count": sum(
					len(matched.get(str(item.get("module", "")), [])) for item in failures
				),
				"executed_module_count": len(results),
				"duration_seconds": round(total_duration, 3),
			},
			"performance": {
				"total_seconds": round(total_duration, 3),
				"modules": {key: round(value, 3) for key, value in module_durations.items()},
			},
			"modules": results,
			"uninterpreted_changes": unmatched,
			"deferred_changes": deferred,
			"failures": failures,
		}


def run_changeset_modules(
	changeset: MutableMapping[str, object],
	validation_config: Optional[Mapping[str, object]] = None,
) -> Dict[str, object]:
	config = validation_config or {}
	context = ModuleContext(
		tdr_root=str(config.get("tdr_root") or ""),
		region_code=str(config.get("region_code") or "TW"),
	)
	return ModuleRegistry().analyze(changeset, context)
