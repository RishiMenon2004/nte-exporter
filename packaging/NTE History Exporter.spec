# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


block_cipher = None
root = Path(SPECPATH).parent
# packaging/icon_cli.png becomes the icon, or packaging/icon.png if it's missing.
# PyInstaller converts it to .ico or .icns with Pillow (in the "build" extra).
# Linux binaries have none.
icon_path = next(
    (path for path in (root / "packaging" / "icon_cli.png", root / "packaging" / "icon.png") if path.exists()),
    None,
)
icon = str(icon_path) if icon_path else None


a = Analysis(
    [str(root / "src" / "nte_history_exporter" / "cli.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[(str(root / "mappings"), "mappings")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="nte-history-exporter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)
