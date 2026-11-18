# PyInstaller spec: one folder with both programs sharing one Python runtime.
#   dist/TaskPill/TaskPill.exe        the app (no console window)
#   dist/TaskPill/taskpill-hook.exe   what Claude Code runs (no console window,
#                                     so nothing flashes on screen per hook)
# Build: pyinstaller --noconfirm --clean packaging/taskpill.spec

from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH is set by PyInstaller)
ICON = str(ROOT / "packaging" / "taskpill.ico")

# Qt parts we never use (keeps the download smaller).
QT_EXCLUDES = [
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtSql", "PySide6.QtPdf",
    "PySide6.QtSvg", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.Qt3DCore",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth",
    "PySide6.QtPositioning", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtTest",
    "tkinter", "unittest", "pydoc",
]

import uiautomation  # noqa: E402

UIA_BIN = Path(uiautomation.__file__).parent / "bin"

app = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "entry_app.py")],
    pathex=[str(ROOT / "src")],
    binaries=[(str(dll), "uiautomation/bin") for dll in UIA_BIN.glob("*.dll")],
    datas=[(str(ROOT / "src" / "taskpill" / "sounds"), "taskpill/sounds")],  # the two chimes
    hiddenimports=["uiautomation", "comtypes", "comtypes.client"],
    excludes=QT_EXCLUDES,
)

# Files Qt's hooks pull in that TaskPill never loads (about 50 MB).
UNUSED = (
    "opengl32sw.dll",  # software OpenGL fallback; we paint with QPainter
    "qt6quick", "qt6qml", "qt6pdf", "qt6network", "qt6opengl", "qt6svg", "qt6virtualkeyboard",
    "qdirect2d.dll", "qminimal.dll", "qoffscreen.dll",  # we only need the qwindows platform
    "qpdf.dll", "qsvg.dll", "qtiff.dll", "qwebp.dll", "qgif.dll", "qicns.dll", "qtga.dll",
    "qwbmp.dll", "qjpeg.dll",
    "pyside6/translations",
)


def _keep(entry) -> bool:
    dest = entry[0].replace("\\", "/").lower()
    return not any(part in dest for part in UNUSED)


app.binaries = [b for b in app.binaries if _keep(b)]
app.datas = [d for d in app.datas if _keep(d)]
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
    icon=ICON,
)
hook_exe = EXE(  # noqa: F821
    PYZ(hook.pure),  # noqa: F821
    hook.scripts,
    [],
    exclude_binaries=True,
    name="taskpill-hook",
    console=False,
    icon=ICON,
)

COLLECT(  # noqa: F821
    app_exe, app.binaries, app.datas,
    hook_exe, hook.binaries, hook.datas,
    name="TaskPill",
)
