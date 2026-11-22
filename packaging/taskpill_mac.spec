# PyInstaller spec for macOS: one TaskPill.app holding both programs.
#   TaskPill.app/Contents/MacOS/TaskPill        the app (menu bar only, no Dock icon)
#   TaskPill.app/Contents/MacOS/taskpill-hook   what Claude Code runs
# Build: packaging/build_macos.sh (makes the icon first, then a .dmg)

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH is set by PyInstaller)
sys.path.insert(0, str(ROOT / "src"))
from taskpill import __version__  # noqa: E402

ICON = str(ROOT / "build" / "taskpill.icns")  # made by build_macos.sh

# Qt parts we never use (keeps the download smaller). Same list as on Windows.
QT_EXCLUDES = [
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSql", "PySide6.QtPdf",
    "PySide6.QtSvg", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.Qt3DCore",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth",
    "PySide6.QtPositioning", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtTest",
    "tkinter", "unittest", "pydoc",
]

app = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "entry_app.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(ROOT / "src" / "taskpill" / "sounds"), "taskpill/sounds")],  # the two chimes
    hiddenimports=["AppKit", "Quartz", "objc", "Foundation"],
    excludes=QT_EXCLUDES,
)
app.datas = [d for d in app.datas if "translations" not in d[0].replace("\\", "/").lower()]

hook = Analysis(  # noqa: F821
    [str(ROOT / "hook" / "taskpill_hook.py")],
    excludes=["tkinter", "unittest", "pydoc"],
)

app_exe = EXE(  # noqa: F821
    PYZ(app.pure),  # noqa: F821
    app.scripts,
    [],
    exclude_binaries=True,
    name="TaskPill",
    console=False,
)
hook_exe = EXE(  # noqa: F821
    PYZ(hook.pure),  # noqa: F821
    hook.scripts,
    [],
    exclude_binaries=True,
    name="taskpill-hook",
    console=False,
)

files = COLLECT(  # noqa: F821
    app_exe, app.binaries, app.datas,
    hook_exe, hook.binaries, hook.datas,
    name="TaskPill",
)

BUNDLE(  # noqa: F821
    files,
    name="TaskPill.app",
    icon=ICON,
    bundle_identifier="io.github.taskpill",
    version=__version__,
    info_plist={
        "CFBundleName": "TaskPill",
        "CFBundleDisplayName": "TaskPill",
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "LSUIElement": True,  # menu bar only: no Dock icon, no app menu
        "LSMinimumSystemVersion": "12.0",  # Qt 6.8 needs macOS 12
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "MIT License",
    },
)
