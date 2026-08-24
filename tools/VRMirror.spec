# PyInstaller spec for VRMirror.
#
# Build with:  python tools/build.py
# or directly: pyinstaller tools/VRMirror.spec --noconfirm

import os
import sys
from pathlib import Path

project_root = Path(SPECPATH).resolve().parent

datas = []

# Bundled adb, if tools/fetch_adb.py has been run.
platform_tools = project_root / "assets" / "platform-tools"
if platform_tools.is_dir():
    datas.append((str(platform_tools), "assets/platform-tools"))

# The optional device server, if server/build.sh has been run.
server_dex = project_root / "assets" / "vrmirror-server.dex"
if server_dex.is_file():
    datas.append((str(server_dex), "assets"))

# PySide6 pulls in a lot by default. Dropping the parts we never touch takes the
# build from roughly 250 MB to roughly 90 MB.
excludes = [
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQml",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSpatialAudio",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "tkinter",
    "matplotlib",
    "numpy.distutils",
    "IPython",
    "pytest",
]

icon_path = project_root / "assets" / "icon.ico"
icon_arg = str(icon_path) if icon_path.is_file() else None

a = Analysis(
    [str(project_root / "run.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=["av"],
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

# One file or one folder. The folder build starts faster because nothing has to
# be unpacked; the single file is easier to hand to someone. Both share the
# analysis above, so the excludes apply either way.
onefile = os.environ.get("VRMIRROR_ONEFILE") == "1"

if onefile:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="VRMirror",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        icon=icon_arg,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="VRMirror",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        icon=icon_arg,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        name="VRMirror",
    )

    if sys.platform == "darwin":
        app = BUNDLE(
            coll,
            name="VRMirror.app",
            icon=str(project_root / "assets" / "icon.icns")
            if (project_root / "assets" / "icon.icns").is_file()
            else None,
            bundle_identifier="dev.vrmirror.app",
            info_plist={
                "NSHighResolutionCapable": True,
                "LSMinimumSystemVersion": "11.0",
            },
        )
