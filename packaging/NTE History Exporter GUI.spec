# -*- mode: python ; coding: utf-8 -*-
#
# Desktop GUI build. Windows and Linux get a single windowed executable,
# dist/nte-history-exporter-gui[.exe]; macOS gets dist/NTE History Exporter.app.

import sys
import tomllib
from pathlib import Path


block_cipher = None
root = Path(SPECPATH).parent
version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
macos = sys.platform == "darwin"


a = Analysis(
    [str(root / "src" / "nte_history_exporter" / "gui" / "__main__.py")],
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

exe_options = dict(
    name="nte-history-exporter-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

if macos:
    # A .app must be a one-folder build: one-file bundles unpack to a temp dir on
    # every launch, and PyInstaller is phasing them out.
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **exe_options)
    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="nte-history-exporter-gui",
    )
    app = BUNDLE(
        coll,
        name="NTE History Exporter.app",
        icon=None,
        bundle_identifier="io.github.rishimenon2004.nte-history-exporter",
        version=version,
        info_plist={
            "CFBundleDisplayName": "NTE History Exporter",
            "CFBundleShortVersionString": version,
            "NSHighResolutionCapable": True,
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        runtime_tmpdir=None,
        **exe_options,
    )
