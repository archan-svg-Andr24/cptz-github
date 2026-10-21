# Сборка StudentPlanner.exe (one-folder, GEN-12, GEN-17).
#
#   py -3.13 -m PyInstaller StudentPlanner.spec --noconfirm
#
# Результат: dist\StudentPlanner\StudentPlanner.exe
#
# exe НЕ подписан цифровой подписью: Windows SmartScreen и антивирусы могут
# показать предупреждение. Это ожидаемое поведение, а не дефект (GEN-17);
# порядок обхода описан в README.md.

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve()

hidden = collect_submodules("student_planner")

a = Analysis(
    [str(ROOT / "StudentPlanner.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # PySide6 тянет за собой лишние модули Qt; берём только используемые.
    excludes=[
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtQml",
        "PySide6.Qt3DCore",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia",
        "PySide6.QtNetworkAuth",
        "PySide6.QtPdf",
        "PySide6.QtBluetooth",
        "PySide6.QtPositioning",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "tkinter",
        "unittest",
        "pytest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StudentPlanner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # оконное приложение, консоль не нужна
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="StudentPlanner",
)
