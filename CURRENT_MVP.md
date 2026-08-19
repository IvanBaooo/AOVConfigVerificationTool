# AOVAutoPacker 当前 MVP 流程说明

## 推荐入口

- 开发运行：`python AOVAutoPackerLocal.py`
- 快捷运行：双击 `run_local_packer.bat`
- 打包 exe：`pyinstaller AOVAutoPackerLocal.spec`

`AOVAutoPackerLocal.py` 是当前正式入口，内部复用已验证的 V10 流程。`AOVAutoPackerMVPCommitV1-V10.py` 保留为迭代历史和排查对照，日常不再直接使用历史入口。

## 当前目标

本地机器发起打包，不由网页派单。网页后端后续负责管理校验规则、归档打包结果、通知状态和历史记录。

当前本地 MVP 先解决四件事：

1. 根据用户选择的区域和 SVN revision 生成本次打包文件列表。
2. 以 `ServerBytes` 为 SVN 锚点读取提交记录，并按区域过滤实际打包内容。
3. 本地执行原 ServerBytes 打包流程，生成 tar/list/md5/report。
4. 输出提交记录校验、区域过滤、包名解析、白名单命中和皮肤配置预检查结果。

## 输入项

### 本地路径

- TdrTable 根目录示例：`C:\path\to\TdrTable`
- ServerBytes 本地目录示例：`C:\path\to\TdrTable\ServerBytes`

当前打包实际读取 ServerBytes 本地目录。dtxml 校验读取 TdrTable 根目录下的 `Xml` 目录。

### SVN 目标

固定使用 ServerBytes 根目录作为 SVN 锚点：

```text
https://svn.example.com/path/to/Tools/TdrTable/ServerBytes
```

这样即使同一个 revision 同时修改多个区域，也可以先完整读取 ServerBytes 下的提交文件，再按用户选择的区域过滤。

### 区域

用户选择区域后，工具会做两件事：

- 用区域决定包名中的区域码。
- 用区域决定 ServerBytes 下的过滤范围。

当前映射：

| ServerBytes 目录 | 区域码 |
| --- | --- |
| `Taiwan` | `TW` |
| `Thailand` | `TH` |
| `Vietnam` | `VN` |
| `Indonesia` | `ID` |

### Revision

支持两种输入：

- 连续范围：`r10001-r10005`
- 指定 revision：`r10001,r10003`

逗号模式表示本次包只包含列出的 revision。中间未列出的 revision 不会被打入包，但会在和上一次对外 revision 的差异检查中作为统计或告警依据。

### 上一次对外信息

网页端后续下发：

- 上一次对外时间。
- 上一次对外 SVN revision。

本地 MVP 先由用户手动输入。提交记录校验会用“上一次对外 revision -> 本次 revision 范围”做差异检查。

### 白名单

用于忽略没有实际打包意义的文件改动。支持一行一条规则：

- 精确路径：`/Taiwan/Databin/Server/Actor/Hero_MD5.txt`
- 通配路径：`/Taiwan/Databin/Server/Actor/Hero_MD5*.txt`

白名单命中的文件不会触发告警，但会记录到 report，方便后续追溯。

## 处理流程

1. 用户在本地工具中输入 ServerBytes 本地目录、SVN ServerBytes 锚点、区域、上次对外 revision、本次 revision。
2. 工具调用 SVN log，读取本次 revision 和对比区间内的 ServerBytes 改动文件。
3. 工具从本次 revision 中提取打包候选文件。
4. 工具按用户选择的区域过滤候选文件，例如选择 `TW` 时仅保留 `/Taiwan/...`。
5. 工具使用过滤后的文件列表执行原有打包逻辑。
6. 工具从 SVN URL 中解析版本号，例如 `NGame_Beta54_...` 解析为 `Beta54`。
7. 工具生成新包名：`sgame_区域_版本_时间戳`，例如 `sgame_TW_Beta54_20260710185537`。
8. 工具执行提交记录校验：
   - 本次指定 revision 内的文件是否能被本地目录找到。
   - 上次对外到本次之间是否存在未进入本次包、但影响选定区域的改动。
   - 白名单文件是否被忽略。
9. 工具执行皮肤配置 MVP 校验：
   - 读取 dtxml。
   - 检查打包涉及内容对应资源的上下架时间、售卖方式。
   - 结合皮肤上下架表和促销特卖表。
10. 工具输出 tar、list、md5、report。

## 输出包名

格式：

```text
sgame_打包区域_打包版本_时间戳
```

示例：

```text
sgame_TW_Beta54_20260710185537
```

说明：

- 打包区域来自用户选择的区域，不再从 revision 自动推断。
- 打包版本来自 SVN URL 中的 `NGame_Beta54_...`。
- 实际打包内容仍然由“本次 revision + 选定区域过滤”共同决定。

## Report 重点字段

当前 report 中建议优先查看：

- `input.region_filter`：原始 ServerBytes 文件数、保留区域文件数、排除其他区域文件数。
- `input.naming`：解析出的区域、版本、最终包名。
- `validation.checks.commit_record`：提交记录校验结果。
- `validation.checks.commit_record.statistics`：SVN 范围统计、未命中日志数量等非告警信息。
- `validation.checks.commit_record.whitelisted_paths`：被白名单忽略的路径。
- `validation.checks.skin_precheck`：皮肤上下架和促销售卖 MVP 校验结果。

## 当前已验证样例

输入：

- 上次对外：`r1698349`
- 本次对外：`r1699919,r1699997`
- 区域：`TW`
- SVN 锚点：ServerBytes 根目录

结果：

- 原始 ServerBytes 文件数：54
- TW 保留文件数：20
- 其他区域排除文件数：34
- 生成包名示例：`sgame_TW_Beta54_20260710185537`
- 白名单 `/Taiwan/Databin/Server/Actor/Hero_MD5*.txt` 命中 3 个文件后，提交记录校验通过。

## 后续待接入

- 网页后端维护校验规则版本，本地启动时检查并拉取最新规则。
- 网页后端维护上一次对外时间和 revision，本地打包时自动读取。
- 打包完成后上传 FTP。
- 打包完成后将 report、包名、revision、区域、校验结果同步到网页后端归档。
- 邮件通知和回复状态跟踪由网页后端负责，Gmail 只作为后续集成能力。
