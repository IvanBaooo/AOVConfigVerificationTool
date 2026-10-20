# PyInstaller spec：把 electron_bridge.py 打成单文件 aov-bridge（Python 侧全标准库）。
# 从仓库根目录运行：pyinstaller packaging/aov_bridge.spec --distpath dist-bridge
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["../electron_bridge.py"],
    pathex=[".."],
    binaries=[],
    datas=[],
    hiddenimports=collect_submodules("rules.impl"),
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="aov-bridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
