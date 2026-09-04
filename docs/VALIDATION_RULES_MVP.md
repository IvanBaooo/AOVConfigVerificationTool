# 校验规则下发 MVP

## 已实现流程

```text
后端发布不可变规则版本
-> 本地启动或切换区域时查询最新规则
-> 校验响应结构与 SHA-256
-> 保存区域缓存
-> 公共规则与区域覆盖规则合并
-> 打包时合并后端白名单与本地白名单
-> Report 和网页归档记录规则版本
```

后端不可用时：

1. 优先使用该区域上次成功缓存。
2. 没有缓存时使用程序内置基础规则。
3. 不阻止本地打包。
4. Report 通过 `validation.rule_set.source` 记录规则来源。

## 后端接口

### 发布规则版本

```http
POST /api/v1/validation-rule-sets
Content-Type: application/json
```

`rule_set_id + version` 是不可变唯一键：

- 相同版本、相同内容：返回 `replayed`。
- 相同版本、不同内容：返回 `409 rule_version_conflict`。

初始示例见 `rules/example_rule_set.json`。

### 查询区域有效规则

```http
GET /api/v1/validation-rules/latest?region_code=TW
```

支持区域：`TW`、`TH`、`VN`、`ID`。

后端先合并公共规则和区域覆盖规则，再返回：

```json
{
  "rule_set": {
    "schema_version": "1.0",
    "rule_set_id": "aov-main",
    "version": "2026.07.27.1",
    "published_at": "2026-07-27T13:00:00Z",
    "region_code": "TW",
    "rules": {
      "path_mappings": [],
      "whitelist_paths": []
    },
    "rule_hash": "..."
  }
}
```

## 本地缓存

默认文件：

```text
rules/cached_rule_set.json
```

规则集 schema 校验在 `rules/sets.py`，拉取/缓存客户端在 `rules/client.py`。
缓存位置以本地 `settings.json` 所在目录为基准。测试时可以通过环境变量覆盖：

```text
AOV_VALIDATION_RULE_CACHE
```

缓存按区域分别保存，只接受通过结构校验和 hash 校验的规则。

## GUI

现有“归档配置”页新增：

- 当前区域规则版本和来源。
- “检查规则更新”按钮。

启动后自动检查一次；切换 TW/TH/VN/ID 时自动加载对应区域规则。日常打包页没有新增输入项。

## Report 与归档

本地 Report：

```text
validation.rule_set.rule_set_id
validation.rule_set.version
validation.rule_set.rule_hash
validation.rule_set.published_at
validation.rule_set.region_code
validation.rule_set.source
```

正式同步到网页后端时保留以上字段，但不会上传：

- 后端连接错误详情
- 本地缓存路径
- 本地配置文件
- Token 或其他账号信息

归档详情的“校验结果”区域会展示规则版本、来源、发布时间和 hash。

## 当前初始规则

已在本地 `8780` 后端发布：

```text
rule_set_id: aov-main
version: 2026.07.27.1
regions: TW / TH / VN / ID
path_mappings: 2
```

当前两条映射对应：

```text
SvrHeroSkinShop.xml -> 英雄皮肤促销表
SvrHeroSkinShop.bytes -> 英雄皮肤促销表
```

后续只需发布新版本补充路径映射和白名单，无需修改本地打包程序。

## 网页规则管理

后台左侧“规则管理”栏目提供规则版本维护：

- 查看不可变版本历史和完整规则详情。
- 从当前版本创建草稿，自动生成 `YYYY.MM.DD.N` 版本号。
- 结构化维护公共规则及 TW/TH/VN/ID 区域覆盖规则。
- 维护路径映射和提交告警白名单，不直接编辑原始 JSON。
- 实时校验必填项、路径格式和重复规则。
- 发布前展示新增、修改、删除和问题数量，并要求人工二次确认。

### 表内容校验规则

规则编辑器中的“表内容校验”与 SVN 路径映射、白名单使用同一版本。
当前 MVP 支持 `skin_sale_window` 类型，执行内容包括：

- 读取 `英雄皮肤促销表.dtxml`。
- 检查长期上下架 Sheet 的上架、下架时间和售卖方式字段。
- 根据 `促销特卖1-5` 关联促销 Sheet 的 `促销特卖ID`。
- 检查短期促销时间窗口与关联记录是否存在。
- 只在本次打包涉及任一 `trigger_paths` 时执行。

每条规则配置：

```json
{
  "id": "skin-sale-window",
  "type": "skin_sale_window",
  "enabled": true,
  "name": "英雄皮肤上下架与促销关联",
  "dtxml_path": "/Xml/Garena/{region}/CommonCore/英雄皮肤促销表.dtxml",
  "main_sheet": "svr下发皮肤上下架表",
  "promotion_sheet": "svr下发皮肤促销特卖",
  "trigger_paths": [
    "/Databin/Server/Shop/SvrHeroSkinShop.xml",
    "/Databin/Server/Shop/SvrHeroSkinShop.bytes"
  ]
}
```

`{region}` 在本地执行时替换为 TW/TH/VN/ID。区域规则使用相同 `id`
覆盖公共规则；将区域规则的 `enabled` 设为 `false` 可以仅对该区域关闭检查。
校验结果继续写入 Report 的 `validation.checks.skin_precheck`，归档只记录所用
规则版本与最终校验结果，不上传本地绝对路径。
草稿只存在于当前浏览器页面，未确认发布时不会写入数据库。发布后的
`rule_set_id + version` 不可修改，后续调整必须新建版本。

读取接口无需 Token：

```http
GET /api/v1/validation-rule-sets?limit=100&offset=0
GET /api/v1/validation-rule-sets/{rule_set_id}/{version}
```

当前 MVP 关闭 Token 时，发布接口仍只接受来自后端所在机器的回环地址
（`127.0.0.1`、`::1` 或 `localhost`），防止局域网其他机器直接修改规则。