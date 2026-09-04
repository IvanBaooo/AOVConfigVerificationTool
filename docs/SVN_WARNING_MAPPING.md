# SVN 告警映射与白名单

## 当前行为

提交记录校验仍以“上次对外 revision、本次所选 revision、SVN log 和实际打包文件列表”为判断依据。
本次改动只增强告警展示和白名单审计，不改变 revision 选包逻辑。

本地 `report.json` 的 `validation.checks.commit_record` 现在包含：

- `warnings`：当前仍需人工处理的提交告警。
- `affected_tables`：从有效告警中提取的可读表名和路径。
- `ignored_changes`：被白名单忽略的原始告警，保留命中的白名单规则。
- `ignored_tables`：被白名单忽略的可读表名和路径。
- `statistics.whitelisted_warning_count`：白名单命中数量。

每条路径告警同时保留：

- `table_name`：可读表名。
- `readable_name`：可读表名与实际文件名。
- `directory`：ServerBytes 相对目录。
- `fixed_path`：完整 ServerBytes 相对路径。
- `mapping_source`：`configured`、`built_in` 或 `file_name`。

## 映射优先级

1. 后端规则中的 `commit_record.path_mappings`。
2. 本地内置映射。
3. 未配置的文件使用文件名去扩展名作为临时表名，并保留目录。

后端规则示例：

```json
{
  "commit_record": {
    "path_mappings": [
      {
        "path_suffix": "/Databin/Server/Event/SvrEvent.xml",
        "module": "活动",
        "table_name": "活动上架表"
      }
    ]
  }
}
```

当前内置了 `SvrHeroSkinShop.xml/.bytes -> 英雄皮肤促销表`。后续可逐步把确认后的
XML 与 dtxml 对应关系放到后端规则中。

## 白名单输入

配置页的 Commit whitelist 支持每行一个规则：

```text
# 注释行
Hero_MD5*.txt
/Taiwan/Databin/Server/Actor/NoImpact.xml
/Taiwan/Databin/Server/Generated/
```

- 文件名：匹配任意目录下的同名文件。
- 完整路径：只匹配该路径。
- `* ? []`：支持通配符。
- 以 `/` 结尾的路径：匹配该目录及其子项。
- `#` 开头：作为注释忽略。

白名单仅消除对应的文件路径告警，不会改变打包文件内容，也不会隐藏审计记录。
