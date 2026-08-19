# AOVAutoPacker Start Here

当前推荐从这里启动：

```powershell
cd C:\Users\admin\Documents\AOVConfigVerification\AOVAutoPacker
python AOVAutoPackerStart.py
```

或双击：

```text
start_packer.bat
```

## 当前默认界面

`AOVAutoPackerStart.py` 会启动 compact GUI，也就是两页式界面：

- `Daily`：日常只填区域和本次 revision。
- `Config`：SVN、本地目录、上次对外 revision、白名单、校验窗口等高级配置。

## 打 exe

建议使用：

```powershell
pyinstaller AOVAutoPackerStart.spec
```

产物名称会是：

```text
AOVAutoPacker.exe
```

## 后续继续点

1. 确认 compact GUI 在当前机器可以正常打包。
2. 将网页后端下发的配置接入 Config 页对应变量。
3. 增加打包后上传 FTP。
4. 增加 report 同步网页后端归档。
5. 后续确认稳定后，再清理旧的 V1-V10 历史入口。
