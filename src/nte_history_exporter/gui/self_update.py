"""Replace the running packaged GUI with a newer release, then start it again.

A running program can be renamed on all three platforms, just not overwritten,
so the new build moves into place and the old one is set aside as "<name>.old",
to be deleted by the next start. Anything that goes wrong before the swap leaves
the install untouched; see docs/gui.md.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

from nte_history_exporter.update_check import RELEASE_DOWNLOAD_URL, ReleaseAsset, UpdateInfo

DOWNLOAD_TIMEOUT_SECONDS = 30
CHUNK_BYTES = 256 * 1024
# The old build stays locked until its process has fully exited.
CLEANUP_ATTEMPTS = 15
CLEANUP_DELAY_SECONDS = 1.0


class UpdateError(Exception):
    """An update could not be applied; the message is shown in the activity log."""


def current_install() -> Path | None:
    """What an update replaces: the executable or .app, or None when run from source."""
    if not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        app = executable.parents[2]  # X.app/Contents/MacOS/executable
        return app if app.suffix == ".app" else None
    return executable


def asset_name(latest_version: str) -> str:
    """The release file holding this platform's GUI; see .github/workflows/release.yml."""
    if sys.platform == "win32":
        return "nte-history-exporter-gui.exe"
    if sys.platform == "darwin":
        return f"nte-history-exporter-gui-v{latest_version.removeprefix('v')}-x86_64-apple-darwin.zip"
    return "nte-history-exporter-gui-linux"


def find_asset(update: UpdateInfo) -> ReleaseAsset | None:
    """The file to install, or None if this build can't update itself to that release."""
    if current_install() is None:
        return None
    name = asset_name(update.latest_version)
    return next((asset for asset in update.assets if asset.name == name), None)


def download(asset: ReleaseAsset, target: Path, progress: Callable[[int], None]) -> Path:
    """Fetch and verify an asset next to ``target``; ``progress`` gets a percentage."""
    if not asset.url.startswith(RELEASE_DOWNLOAD_URL):
        raise UpdateError("unexpected download address")
    expected = asset.digest.removeprefix("sha256:").lower()
    if not asset.digest.startswith("sha256:") or len(expected) != 64:
        raise UpdateError("the release has no checksum")

    path = _sibling(target, "download")
    digest = hashlib.sha256()
    received = 0
    request = urllib.request.Request(asset.url, headers={"User-Agent": "nte-history-exporter"})
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response, path.open("wb") as file:
        while chunk := response.read(CHUNK_BYTES):
            file.write(chunk)
            digest.update(chunk)
            received += len(chunk)
            if asset.size:
                progress(min(100, received * 100 // asset.size))

    if digest.hexdigest() != expected:
        path.unlink(missing_ok=True)
        raise UpdateError("the download failed its checksum")
    return path


def install(downloaded: Path, target: Path) -> None:
    """Swap the new build in and start it, putting the old one back if that fails."""
    new = _unpack(downloaded, target)
    old = _sibling(target, "old")
    _remove(old)
    os.replace(target, old)
    try:
        os.replace(new, target)
        _start(target)
    except OSError:
        _remove(target)
        os.replace(old, target)
        raise


def remove_leftovers(attempts: int = CLEANUP_ATTEMPTS) -> None:
    """Delete what an update left behind, waiting for the old build to exit."""
    target = current_install()
    if target is None:
        return
    leftovers = [_sibling(target, suffix) for suffix in ("old", "download", "unpacked")]
    for attempt in range(attempts):
        for path in leftovers:
            try:
                _remove(path)
            except OSError:
                pass
        if not any(path.exists() for path in leftovers):
            return
        if attempt + 1 < attempts:
            time.sleep(CLEANUP_DELAY_SECONDS)


def _sibling(target: Path, suffix: str) -> Path:
    return target.with_name(f"{target.name}.{suffix}")


def _unpack(downloaded: Path, target: Path) -> Path:
    """Turn the download into a ready-to-run build beside ``target``."""
    if sys.platform != "darwin":
        downloaded.chmod(downloaded.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return downloaded

    # ditto, not zipfile: a .app relies on the symlinks and modes it restores.
    folder = _sibling(target, "unpacked")
    _remove(folder)
    subprocess.run(["ditto", "-x", "-k", str(downloaded), str(folder)], check=True, capture_output=True)
    apps = list(folder.glob("*.app"))
    if len(apps) != 1:
        raise UpdateError("the download has no app in it")
    return apps[0]


def _start(target: Path) -> None:
    # Without this the new build would reuse the old one's unpacked files.
    env = {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    command = ["open", "-n", str(target)] if sys.platform == "darwin" else [str(target)]
    subprocess.Popen(command, env=env)


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
