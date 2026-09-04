"""rules/impl 规则测试的共享 fixture 与构造 helper。"""
from __future__ import annotations

from pathlib import Path

from rules.registry import default_incident_content_checks


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "incident_derived_rules.json"

ITEM_COLUMNS = [
    "ID", "名称", "是否是隐藏道具", "活动ID", "限时道具有效期", "可使用结束日期",
]

ITEM_TOUCH_PATHS = ["Taiwan/Databin/Server/Item/SvrItem.bytes"]


def write_item_dtxml(root: Path, rows: list[dict[str, str]]) -> Path:
    dtxml_dir = root / "Xml" / "Garena" / "TW" / "CommonCore"
    dtxml_dir.mkdir(parents=True, exist_ok=True)
    path = dtxml_dir / "41.svr下发道具信息表_Test.dtxml"
    columns_xml = "".join(f'<Column Name="{name}" />' for name in ITEM_COLUMNS)
    rows_xml = ""
    for row in rows:
        cells = "".join(f'<Cell Name="{name}">{value}</Cell>' for name, value in row.items())
        rows_xml += f"<Row>{cells}</Row>"
    path.write_text(
        f'<Root><Sheet Name="道具信息"><Columns>{columns_xml}</Columns>{rows_xml}</Sheet></Root>',
        encoding="utf-8",
    )
    return path


def make_config(tdr_root: Path, **extra: object) -> dict[str, object]:
    config: dict[str, object] = {
        "region_code": "TW",
        "tdr_root": str(tdr_root),
        "content_checks": default_incident_content_checks(),
    }
    config.update(extra)
    return config


def make_changeset(*item_ids: str) -> list[dict[str, object]]:
    """构造道具信息表的行级变更，驱动「只校验提交内容」的规则触发。"""
    return [
        {
            "sheet": "道具信息",
            "file_name": "Item/SvrItem.bytes",
            "change_type": "modified",
            "business_key": {"columns": ["ID"], "values": [item_id], "display": f"ID={item_id}"},
        }
        for item_id in item_ids
    ]


SKIN_LISTING_COLUMNS = [
    "ID", "英雄ID", "皮肤ID", "皮肤名称",
    "是否可点券购买", "点券价格", "是否可皮肤点购买", "是否可钻石购买", "是否支持混合支付",
]
SKIN_PROMO_COLUMNS = [
    "促销特卖ID", "皮肤ID",
    "是否可点券购买", "点券价格", "是否可皮肤点购买", "是否可钻石购买", "是否支持混合支付",
]
SKIN_LISTING_SHEET = "svr下发皮肤上下架表"
SKIN_PROMO_SHEET = "svr下发皮肤促销特卖"


def sheet_xml(name: str, columns: list[str], rows: list[dict[str, str]]) -> str:
    columns_xml = "".join(f'<Column Name="{column}" />' for column in columns)
    rows_xml = ""
    for row in rows:
        cells = "".join(f'<Cell Name="{key}">{value}</Cell>' for key, value in row.items())
        rows_xml += f"<Row>{cells}</Row>"
    return f'<Sheet Name="{name}"><Columns>{columns_xml}</Columns>{rows_xml}</Sheet>'


def write_skin_dtxml(
    root: Path,
    listing_rows: list[dict[str, str]],
    promo_rows: list[dict[str, str]] | None = None,
) -> Path:
    dtxml_dir = root / "Xml" / "Garena" / "TW" / "CommonCore"
    dtxml_dir.mkdir(parents=True, exist_ok=True)
    path = dtxml_dir / "英雄皮肤促销表.dtxml"
    path.write_text(
        "<Root>"
        + sheet_xml(SKIN_LISTING_SHEET, SKIN_LISTING_COLUMNS, listing_rows)
        + sheet_xml(SKIN_PROMO_SHEET, SKIN_PROMO_COLUMNS, promo_rows or [])
        + "</Root>",
        encoding="utf-8",
    )
    return path


def skin_check() -> dict[str, object]:
    return next(
        check for check in default_incident_content_checks()
        if check["type"] == "skin_sale_change_check"
    )


def skin_changeset(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    """构造皮肤促销表行级变更（before/after 行数据直接驱动规则判定）。"""
    changes: list[dict[str, object]] = []
    for entry in entries:
        after = entry.get("after") if isinstance(entry.get("after"), dict) else None
        before = entry.get("before") if isinstance(entry.get("before"), dict) else None
        row = after or before or {}
        skin_id = str(row.get("皮肤ID", ""))
        changes.append({
            "sheet": entry["sheet"],
            "file_name": "英雄皮肤促销表.dtxml",
            "change_type": entry.get("change_type", "modified"),
            "changed_fields": entry.get("changed_fields", []),
            "before": before,
            "after": after,
            "business_key": {"columns": ["皮肤ID"], "values": [skin_id], "display": f"皮肤ID={skin_id}"},
        })
    return changes
