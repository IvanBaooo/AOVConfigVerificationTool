"""Showcase 演示工作区：不依赖 SVN 的规则命中演示。

思路：
- `baseline/` 与 `current/` 是真实 TdrTable 备份的两份 APFS 克隆（cp -c，几乎不占空间）
- 演示场景直接改 `current/` 下的 dtxml 拷贝，永不提交 SVN
- 运行时 diff 两份目录 → 合成 svn log 文本 → 用本地 content_loader 喂给
  `build_dtxml_changeset`，后续 module 解读与规则校验与真实打包完全一致

目录布局（root 默认为 electron-app 同级的 `_accept/showcase/`）：

    root/
      baseline/TdrTable/Xml/Garena/TW/...   # 克隆自真实备份
      current/TdrTable/Xml/Garena/TW/...    # 克隆 + 场景修改（可手工再编辑）
      scenarios.json                        # 场景清单与说明
"""

from __future__ import annotations

import filecmp
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Mapping, Optional
from xml.etree import ElementTree as ET

from svn_dtxml_changeset import build_dtxml_changeset

REGION = "TW"
# 演示工作区克隆范围（相对 TdrTable 根）：区域表 + 公共表（module 关联索引会读）
CLONE_SUBDIRS = ("Xml/Garena/TW", "Xml/CommonCore")

# 合成 log 的仓库路径前缀（仅展示用，不访问真实 SVN）
REPO_PREFIX = "/HONTeam/HON_proj/branches/PUB/SHOWCASE/Tools/TdrTable"

ITEM_DFXML_NAME = "41.svr下发道具信息表_Syndra.dtxml"
SKIN_DFXML_NAME = "英雄皮肤促销表.dtxml"
DAILY_ACTIVITY_NAME = "日常活动表.dtxml"
COMMON_CORE = os.path.join("Xml", "Garena", "TW", "CommonCore")

# dtxml 改动对应的 ServerBytes 产出（01 提交校验的「已打入包」清单）
BYTES_BY_DFXML = {
    ITEM_DFXML_NAME: [
        "ServerBytes/Taiwan/Databin/Server/Item/SvrItem.bytes",
        "ServerBytes/Taiwan/Databin/Server/Item/SvrItem.xml",
    ],
    SKIN_DFXML_NAME: [
        "ServerBytes/Taiwan/Databin/Server/Shop/SvrHeroSkinShop.bytes",
        "ServerBytes/Taiwan/Databin/Server/Shop/SvrHeroSkinShop.xml",
    ],
}

# 01 间隔提交校验演示条目：在 log 里、但不在打包清单里 → 遗漏告警
# Hero_MD5 命中用户白名单（豁免归档）；ResSvr2CltIluaCfg 命中高危名单（置顶标红）
GAP_DEMO_ENTRIES = [
    "ServerBytes/Taiwan/Databin/Server/Actor/Hero_MD5_Android.txt",
    "ServerBytes/Taiwan/Databin/Server/Actor/Hero_MD5_IOS.txt",
    "ServerBytes/Taiwan/Databin/Server/Global/ResSvr2CltIluaCfg.xml",
    "ServerBytes/Taiwan/Databin/Server/Global/ResSvr2CltIluaCfg.bytes",
]

SCENE_DESCRIPTIONS = [
    {"id": "hidden_item", "title": "隐藏道具", "description": "把一条道具改为隐藏道具，命中「隐藏道具识别」告警"},
    {"id": "expiry_conflict", "title": "有效期冲突", "description": "道具限时有效期落在关联活动期间内，命中「有效期关联校验」告警"},
    {"id": "skin_sale_flip", "title": "售卖方式翻转", "description": "皮肤「是否可点券购买」否→是，命中「皮肤售卖方式变更校验」告警"},
    {"id": "skin_low_price", "title": "低价风险", "description": "皮肤点券价格改为 60（<100），命中低价告警"},
    {"id": "skin_promo_add", "title": "新增促销", "description": "新增一条促销并关联皮肤，转人工确认"},
    {"id": "skin_row_delete", "title": "删除促销行", "description": "删除一条促销特卖行，命中删行告警"},
    {"id": "commit_gap", "title": "间隔遗漏", "description": "合成 4 条未打入包的提交：Hero_MD5 ×2（白名单豁免）+ ResSvr2CltIluaCfg（高危置顶）"},
]


# ---------------------------------------------------------------------------
# 工作区初始化
# ---------------------------------------------------------------------------

def workspace_layout(root: Path) -> Dict[str, Path]:
    return {
        "root": root,
        "baseline": root / "baseline" / "TdrTable",
        "current": root / "current" / "TdrTable",
        "manifest": root / "scenarios.json",
    }


def _clone_tree(src: Path, dst: Path) -> None:
    """APFS clonefile 克隆（几乎不占空间）；非 APFS 退回普通拷贝。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    completed = subprocess.run(
        ["cp", "-Rc", str(src), str(dst)], capture_output=True, check=False,
    )
    if completed.returncode != 0:
        shutil.copytree(src, dst)


def _load_manifest(root: Path) -> List[Dict[str, object]]:
    manifest = workspace_layout(root)["manifest"]
    if not manifest.is_file():
        return []
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [item for item in data.get("scenes", []) if isinstance(item, dict)]


def _save_manifest(root: Path, scenes: List[Dict[str, object]]) -> None:
    manifest = workspace_layout(root)["manifest"]
    manifest.write_text(
        json.dumps({"scenes": scenes}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# dtxml 行编辑工具（只作用于 current/ 拷贝）
# ---------------------------------------------------------------------------

def _open_sheet(path: Path, sheet_name: str):
    tree = ET.parse(str(path))
    root = tree.getroot()
    sheet = None
    for candidate in root.iter("Sheet"):
        if candidate.get("Name") == sheet_name:
            sheet = candidate
            break
    if sheet is None:
        raise ValueError(f"{path.name} 中找不到 sheet：{sheet_name}")
    return tree, sheet


def _cell(row: ET.Element, name: str) -> Optional[ET.Element]:
    for cell in row.iter("Cell"):
        if cell.get("Name") == name:
            return cell
    return None


def _get(row: ET.Element, name: str) -> str:
    cell = _cell(row, name)
    return (cell.text or "").strip() if cell is not None else ""


def _set(row: ET.Element, name: str, value: str) -> None:
    cell = _cell(row, name)
    if cell is None:
        cell = ET.SubElement(row, "Cell")
        cell.set("Name", name)
    cell.text = value


def _rows(sheet: ET.Element) -> List[ET.Element]:
    return [node for node in sheet.iter("Row")]


def _write(tree: ET.ElementTree, path: Path) -> None:
    """保留 BOM 写回（真实 dtxml 均为 utf-8 带 BOM）。"""
    import io
    buffer = io.BytesIO()
    tree.write(buffer, encoding="utf-8", xml_declaration=True)
    path.write_bytes(b"\xef\xbb\xbf" + buffer.getvalue())


def _is_placeholder(row: ET.Element) -> bool:
    """占位行（ID=0 或名称含「占位」）不参与演示改造。"""
    return _get(row, "ID") == "0" or "占位" in _get(row, "名称") or "占位" in _get(row, "皮肤名称")


def _compact(dt: datetime) -> str:
    return dt.strftime("%Y%m%d%H%M%S")


# ---------------------------------------------------------------------------
# 演示场景（全部作用于 current/ 拷贝）
# ---------------------------------------------------------------------------

def _scene_hidden_item(current: Path) -> Dict[str, object]:
    path = current / COMMON_CORE / ITEM_DFXML_NAME
    tree, sheet = _open_sheet(path, "道具信息")
    for row in _rows(sheet):
        if _get(row, "ID") and not _is_placeholder(row) and _get(row, "是否是隐藏道具") not in {"1", "true", "是"}:
            _set(row, "是否是隐藏道具", "1")
            _write(tree, path)
            return {"applied": True, "detail": f"道具 { _get(row, 'ID') }（{_get(row, '名称')}）改为隐藏道具"}
    return {"applied": False, "detail": "道具表中没有可改造的行"}


def _scene_expiry_conflict(current: Path) -> Dict[str, object]:
    item_path = current / COMMON_CORE / ITEM_DFXML_NAME
    activity_path = current / COMMON_CORE / DAILY_ACTIVITY_NAME
    # 先在活动表里找一个有起止时间的活动
    activity_tree = ET.parse(str(activity_path))
    activity = None
    for sheet in activity_tree.getroot().iter("Sheet"):
        for row in _rows(sheet):
            start, end = _get(row, "开始时间"), _get(row, "结束时间")
            if _get(row, "活动ID") and len(start) == 14 and len(end) == 14:
                activity = {"id": _get(row, "活动ID"), "name": _get(row, "活动名称") or _get(row, "活动标题"),
                            "start": start, "end": end}
                break
        if activity:
            break
    if not activity:
        return {"applied": False, "detail": "日常活动表中找不到含起止时间的活动"}

    tree, sheet = _open_sheet(item_path, "道具信息")
    for row in _rows(sheet):
        if _get(row, "ID") and not _is_placeholder(row):
            start_dt = datetime.strptime(activity["start"], "%Y%m%d%H%M%S")
            expiry = _compact(start_dt + timedelta(hours=1))
            _set(row, "活动ID", str(activity["id"]))
            _set(row, "限时道具有效期", expiry)
            _write(tree, item_path)
            return {
                "applied": True,
                "detail": (
                    f"道具 {_get(row, 'ID')}（{_get(row, '名称')}）关联活动 {activity['id']}，"
                    f"有效期设为 {expiry}（活动期间 {activity['start']}~{activity['end']} 内）"
                ),
            }
    return {"applied": False, "detail": "道具表中没有可改造的行"}


def _scene_skin_sale_flip(current: Path) -> Dict[str, object]:
    path = current / COMMON_CORE / SKIN_DFXML_NAME
    tree, sheet = _open_sheet(path, "svr下发皮肤上下架表")
    for row in _rows(sheet):
        if _get(row, "皮肤ID") and not _is_placeholder(row) and _get(row, "是否可点券购买") == "否":
            _set(row, "是否可点券购买", "是")
            _write(tree, path)
            return {"applied": True, "detail": f"皮肤 {_get(row, '皮肤ID')}（{_get(row, '皮肤名称')}）点券购买 否→是"}
    return {"applied": False, "detail": "上下架表中没有「不可点券购买」的皮肤行"}


def _scene_skin_low_price(current: Path) -> Dict[str, object]:
    path = current / COMMON_CORE / SKIN_DFXML_NAME
    tree, sheet = _open_sheet(path, "svr下发皮肤上下架表")
    candidates = [
        row for row in _rows(sheet)
        if _get(row, "皮肤ID") and not _is_placeholder(row)
        and _get(row, "是否可点券购买") == "是"
        and _get(row, "点券价格").isdigit() and int(_get(row, "点券价格")) >= 100
    ]
    if not candidates:
        return {"applied": False, "detail": "上下架表中没有可改造的高价行"}
    row = candidates[-1]
    price = _get(row, "点券价格")
    _set(row, "点券价格", "60")
    _write(tree, path)
    return {"applied": True, "detail": f"皮肤 {_get(row, '皮肤ID')}（{_get(row, '皮肤名称')}）点券价格 {price}→60"}


def _scene_skin_row_delete(current: Path) -> Dict[str, object]:
    path = current / COMMON_CORE / SKIN_DFXML_NAME
    tree, sheet = _open_sheet(path, "svr下发皮肤促销特卖")
    rows = _rows(sheet)
    victim = None
    for row in rows:
        if _get(row, "促销特卖ID") and _get(row, "皮肤ID"):
            victim = row
            break
    if victim is None:
        return {"applied": False, "detail": "促销表中没有可删除的行"}
    detail = f"删除促销 {_get(victim, '促销特卖ID')}（皮肤ID {_get(victim, '皮肤ID')}）"
    for parent in sheet.iter():
        if victim in list(parent):
            parent.remove(victim)
            break
    _write(tree, path)
    return {"applied": True, "detail": detail}


def _scene_skin_promo_add(current: Path) -> Dict[str, object]:
    path = current / COMMON_CORE / SKIN_DFXML_NAME
    # 取一个上下架行 ID 作为关联对象（促销表的「皮肤ID」引用上下架行 ID）
    _, listing_sheet = _open_sheet(path, "svr下发皮肤上下架表")
    listing_id = ""
    for row in _rows(listing_sheet):
        if _get(row, "ID") and _get(row, "皮肤名称") and not _is_placeholder(row):
            listing_id = _get(row, "ID")
    if not listing_id:
        return {"applied": False, "detail": "上下架表中没有可关联的行"}

    tree, sheet = _open_sheet(path, "svr下发皮肤促销特卖")
    existing_ids = {_get(row, "促销特卖ID") for row in _rows(sheet)}
    new_id = str(max([int(x) for x in existing_ids if x.isdigit()] or [990000]) + 1)
    template = None
    for row in _rows(sheet):
        if _get(row, "促销特卖ID"):
            template = row
            break
    if template is None:
        return {"applied": False, "detail": "促销表中没有可复制的模板行"}
    new_row = ET.fromstring(ET.tostring(template))
    _set(new_row, "促销特卖ID", new_id)
    _set(new_row, "皮肤ID", listing_id)
    sheet.append(new_row)
    _write(tree, path)
    return {"applied": True, "detail": f"新增促销 {new_id}，关联上下架行 {listing_id}"}


SCENE_RUNNERS = {
    "hidden_item": _scene_hidden_item,
    "expiry_conflict": _scene_expiry_conflict,
    "skin_sale_flip": _scene_skin_sale_flip,
    "skin_low_price": _scene_skin_low_price,
    "skin_row_delete": _scene_skin_row_delete,
    "skin_promo_add": _scene_skin_promo_add,
}


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------

def init_workspace(root: Path, source_tdr_root: Path, *, force: bool = False) -> Dict[str, object]:
    """初始化/重置演示工作区：克隆数据 + 应用全部场景。"""
    layout = workspace_layout(root)
    if layout["current"].exists() and not force:
        return {"initialized": True, "reused": True, "scenes": _load_manifest(root)}

    for key in ("baseline", "current"):
        target = layout[key]
        if target.exists():
            shutil.rmtree(target)
        for sub in CLONE_SUBDIRS:
            src = source_tdr_root / sub
            if src.is_dir():
                _clone_tree(src, target / sub)

    scenes: List[Dict[str, object]] = []
    for meta in SCENE_DESCRIPTIONS:
        runner = SCENE_RUNNERS.get(meta["id"])
        outcome = runner(layout["current"]) if runner else {"applied": True, "detail": "合成 log 条目（见运行结果 01 区块）"}
        scenes.append({**meta, **outcome})
    _save_manifest(root, scenes)
    return {"initialized": True, "reused": False, "scenes": scenes}


def showcase_status(root: Path) -> Dict[str, object]:
    layout = workspace_layout(root)
    initialized = layout["current"].is_dir()
    return {
        "initialized": initialized,
        "workspace": str(root),
        "scenes": _load_manifest(root) if initialized else [],
        "scene_catalog": SCENE_DESCRIPTIONS,
    }


def diff_workspace(root: Path) -> List[Dict[str, str]]:
    """对比 current/ 与 baseline/，返回 dtxml 变更 [{action, path}]（path 相对 TdrTable 根）。"""
    layout = workspace_layout(root)
    baseline, current = layout["baseline"], layout["current"]
    changes: List[Dict[str, str]] = []
    seen = set()
    for dirpath, _dirnames, filenames in os.walk(current):
        for name in filenames:
            if not name.endswith(".dtxml"):
                continue
            cur = Path(dirpath) / name
            rel = cur.relative_to(current)
            seen.add(str(rel))
            base = baseline / rel
            if not base.exists():
                changes.append({"action": "A", "path": str(rel)})
            elif not filecmp.cmp(cur, base, shallow=False):
                changes.append({"action": "M", "path": str(rel)})
    for dirpath, _dirnames, filenames in os.walk(baseline):
        for name in filenames:
            if not name.endswith(".dtxml"):
                continue
            rel = (Path(dirpath) / name).relative_to(baseline)
            if str(rel) not in seen:
                changes.append({"action": "D", "path": str(rel)})
    return sorted(changes, key=lambda item: item["path"])


def synthesize_svn_log(
    changes: List[Dict[str, str]],
    *,
    current_revision: int,
    baseline_revision: int,
) -> str:
    """把目录 diff 合成 svn log -v 文本（附带 01 演示的间隔遗漏条目）。"""
    blocks: List[str] = []
    current_lines = []
    for change in changes:
        repo_path = f"{REPO_PREFIX}/{change['path']}"
        current_lines.append(f"   {change['action']} {repo_path}")
        for bytes_rel in BYTES_BY_DFXML.get(os.path.basename(change["path"]), []):
            current_lines.append(f"   M {REPO_PREFIX}/{bytes_rel}")
    blocks.append(
        f"r{current_revision} | showcase | 2026-09-01 12:00:00 +0800\n"
        "Changed paths:\n" + "\n".join(current_lines) + "\n\nshowcase 当前提交\n"
        + "-" * 72
    )
    gap_revision = baseline_revision + 1 if baseline_revision + 1 < current_revision else current_revision
    gap_lines = "\n".join(f"   M {REPO_PREFIX}/{rel}" for rel in GAP_DEMO_ENTRIES)
    blocks.append(
        f"r{gap_revision} | showcase | 2026-09-01 11:00:00 +0800\n"
        "Changed paths:\n" + gap_lines + "\n\nshowcase 间隔提交（演示遗漏/白名单/高危）\n"
        + "-" * 72
    )
    return "\n".join(blocks) + "\n"


def make_local_content_loader(root: Path, current_revision: int):
    """content_loader(path, revision)：>= 当前版本读 current/，否则读 baseline/。"""
    layout = workspace_layout(root)

    def _load(changed_path: str, revision: int) -> bytes:
        normalized = changed_path.replace("\\", "/")
        marker = "TdrTable/"
        index = normalized.find(marker)
        rel = normalized[index + len(marker):] if index >= 0 else normalized.lstrip("/")
        base = layout["current"] if revision >= current_revision else layout["baseline"]
        return (base / rel).read_bytes()

    return _load


def build_showcase_changeset(
    root: Path,
    *,
    log_text: str,
    current_revision: int,
    region_code: str = REGION,
) -> Dict[str, object]:
    """用本地 content_loader 生成 changeset（全程不访问 SVN）。"""
    return build_dtxml_changeset(
        log_text=log_text,
        revision_spec=str(current_revision),
        tdr_svn_target="showcase://local",
        region_code=region_code,
        content_loader=make_local_content_loader(root, current_revision),
    )


# ---------------------------------------------------------------------------
# 行编辑器 API（阶段二）：只作用于 current/ 演示副本
# ---------------------------------------------------------------------------

ROW_KEY_COLUMNS = ("ID", "促销特卖ID", "活动ID", "礼包ID", "道具ID", "皮肤ID")
ROW_LABEL_COLUMNS = ("名称", "皮肤名称", "活动名称", "活动标题", "礼包名称")


def _resolve_table(root: Path, file_name: str) -> Path:
    """把表文件名解析到 current/ 拷贝内，防目录逃逸。"""
    base = (workspace_layout(root)["current"] / COMMON_CORE).resolve()
    candidate = (base / os.path.basename(file_name)).resolve()
    if candidate.parent != base or not candidate.is_file():
        raise ValueError(f"演示工作区中找不到表：{file_name}")
    return candidate


def list_tables(root: Path) -> List[Dict[str, object]]:
    """演示副本中的 dtxml 表清单。"""
    base = workspace_layout(root)["current"] / COMMON_CORE
    if not base.is_dir():
        return []
    return [
        {"file_name": path.name, "size": path.stat().st_size}
        for path in sorted(base.glob("*.dtxml"))
    ]


def _parse_sheet_rows(path: Path, sheet_name: str):
    tree, sheet = _open_sheet(path, sheet_name)
    columns = [column.get("Name") for column in sheet.iter("Column") if column.get("Name")]
    rows = []
    for index, row in enumerate(_rows(sheet)):
        cells = {cell.get("Name"): (cell.text or "") for cell in row.iter("Cell") if cell.get("Name")}
        key = next((cells[name].strip() for name in ROW_KEY_COLUMNS if cells.get(name, "").strip()), "")
        label = next((cells[name].strip() for name in ROW_LABEL_COLUMNS if cells.get(name, "").strip()), "")
        rows.append({"index": index, "key": key, "label": label, "cells": cells})
    return tree, sheet, columns, rows


def list_sheets(root: Path, file_name: str) -> List[Dict[str, object]]:
    path = _resolve_table(root, file_name)
    tree = ET.parse(str(path))
    sheets = []
    for sheet in tree.getroot().iter("Sheet"):
        name = sheet.get("Name") or ""
        if name:
            sheets.append({"name": name, "row_count": len(_rows(sheet))})
    return sheets


def list_rows(
    root: Path,
    file_name: str,
    sheet_name: str,
    *,
    keyword: str = "",
    offset: int = 0,
    limit: int = 100,
) -> Dict[str, object]:
    path = _resolve_table(root, file_name)
    _tree, _sheet, columns, rows = _parse_sheet_rows(path, sheet_name)
    if keyword.strip():
        needle = keyword.strip().casefold()
        rows = [
            row for row in rows
            if needle in row["key"].casefold()
            or needle in row["label"].casefold()
            or any(needle in value.casefold() for value in row["cells"].values())
        ]
    total = len(rows)
    window = rows[max(offset, 0): max(offset, 0) + max(1, limit)]
    return {"columns": columns, "rows": window, "total": total, "offset": offset, "limit": limit}


def update_row(root: Path, file_name: str, sheet_name: str, row_index: int, changes: Mapping[str, object]) -> Dict[str, object]:
    path = _resolve_table(root, file_name)
    tree, sheet = _open_sheet(path, sheet_name)
    rows = _rows(sheet)
    if not (0 <= row_index < len(rows)):
        raise ValueError(f"行序号越界：{row_index}（共 {len(rows)} 行）")
    row = rows[row_index]
    applied = 0
    for column, value in changes.items():
        _set(row, str(column), str(value))
        applied += 1
    _write(tree, path)
    return {"updated": applied, "row_index": row_index}


def delete_row(root: Path, file_name: str, sheet_name: str, row_index: int) -> Dict[str, object]:
    path = _resolve_table(root, file_name)
    tree, sheet = _open_sheet(path, sheet_name)
    rows = _rows(sheet)
    if not (0 <= row_index < len(rows)):
        raise ValueError(f"行序号越界：{row_index}（共 {len(rows)} 行）")
    victim = rows[row_index]
    for parent in sheet.iter():
        if victim in list(parent):
            parent.remove(victim)
            break
    _write(tree, path)
    return {"deleted": True, "row_index": row_index}


def add_row(root: Path, file_name: str, sheet_name: str, template_index: int) -> Dict[str, object]:
    """以 template_index 行为模板复制追加一行，返回新行序号。"""
    path = _resolve_table(root, file_name)
    tree, sheet = _open_sheet(path, sheet_name)
    rows = _rows(sheet)
    if not (0 <= template_index < len(rows)):
        raise ValueError(f"模板行序号越界：{template_index}（共 {len(rows)} 行）")
    new_row = ET.fromstring(ET.tostring(rows[template_index]))
    sheet.append(new_row)
    _write(tree, path)
    return {"added": True, "row_index": len(rows)}
