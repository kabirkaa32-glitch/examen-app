# -*- mode: python ; coding: utf-8 -*-
# Build:  python tools/fetch_assets.py && python tools/pack_renderer.py && pyinstaller --noconfirm --clean guard_app.spec
# Debug build with a console window:  set GUARD_CONSOLE=1  (then build)
import os

APP_NAME = "GuardApp"
ROOT_DIR = os.path.abspath(SPECPATH)
ICON = os.path.join(ROOT_DIR, "assets", "icon.ico")
CONSOLE = os.environ.get("GUARD_CONSOLE") == "1"

if not os.path.exists(os.path.join(ROOT_DIR, "_renderer_pack.py")):
    raise SystemExit("Run first: python tools/pack_renderer.py")
if not os.path.exists(ICON):
    raise SystemExit("assets/icon.ico is missing - the EXE would get the default icon")

datas = [("schema.sql", "."), ("assets/icon.png", "assets"), ("assets/icon.ico", "assets")]
if os.path.isdir(os.path.join(ROOT_DIR, "fonts")):
    datas.append(("fonts", "fonts"))          # خطوط الطباعة (تُحمَّل أثناء البناء)

a = Analysis(
    ["app.py"],
    pathex=[ROOT_DIR],
    binaries=[],
    datas=datas,                               # renderer is embedded via _renderer_pack.py
    hiddenimports=[
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebChannel",
        "PySide6.QtNetwork",
        "PySide6.QtPrintSupport",
        "_renderer_pack",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    strip=False,
    upx=False,
    console=CONSOLE,
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
