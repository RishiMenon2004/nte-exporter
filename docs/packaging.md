# Packaging

## Windows local build

Build the Windows console executable with:

```powershell
.\tools\build-windows.cmd
```

The output is:

```text
dist\nte-history-exporter.exe
```

Run live capture from an elevated PowerShell prompt:

```powershell
.\dist\nte-history-exporter.exe --live
```

### Desktop GUI

The GUI has its own windowed spec, `packaging/NTE History Exporter GUI.spec`.
`tools\build-windows.cmd` builds it after the CLI. To build only the GUI:

```powershell
.\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm "packaging\NTE History Exporter GUI.spec"
```

| Platform | Output |
| -------- | ------ |
| Windows | `dist\nte-history-exporter-gui.exe` (one file, no console) |
| Linux | `dist/nte-history-exporter-gui` (one file) |
| macOS | `dist/NTE History Exporter.app` (one-folder build in a bundle; its version comes from `pyproject.toml`) |

A windowed build has no console to print `--help` to, so it accepts
`--smoke-test` instead. That builds the whole window, closes it, and exits 0
on success or 1 on failure. Run it with `start /wait` on Windows (see
`build-windows.cmd`) or under `xvfb-run` on a headless Linux machine.

See [gui.md](gui.md) for runtime permissions on each platform.

## Packet capture runtime

Windows live capture defaults to `--capture-backend auto`, which tries an installed system Npcap runtime first, then the built-in raw-socket backend. If `--capture-backend libpcap` is specified, raw fallback is disabled. If `--capture-backend raw` is specified, only the Windows raw-socket backend is used.

Npcap is Windows-only; Linux and macOS use the system libpcap runtime.

The GitHub Actions release does not download or bundle Npcap. The Windows executable can use a user's installed Npcap runtime when present, then falls back to raw sockets. A future pktmon backend can provide the same kind of no-extra-install Windows path that stardb-exporter uses.

Npcap is not committed or bundled by default. Windows users who want the Npcap backend should install Npcap separately. Users who do not install Npcap can still use the Windows raw-socket fallback.

## Cross-platform CI shape

Use one GitHub Actions job per OS. PyInstaller must build on the target platform, so Windows produces `.exe`, macOS produces a macOS binary, and Linux produces a Linux binary.

This repository has a manual release workflow at:

```text
.github\workflows\release.yml
```

It builds Windows, Linux, and macOS artifacts, then publishes a `v<version>` GitHub release with raw binaries and versioned zip files.

Each build job builds the CLI and then the GUI, and smoke-tests both: the CLI
with `--help`, the GUI with `--smoke-test` (under `xvfb-run` on Linux). The
macOS `.app` is zipped with `ditto` on the macOS runner itself, because
artifact upload drops the executable bits and symlinks a bundle needs. The
release job only renames that zip.

Running the workflow from any branch other than `main` publishes or updates a
`dev-v<version>` pre-release instead. That is the way to try new builds before
a real release, and the in-app update check ignores pre-releases.

Linux runners install the libpcap runtime for parity with live-capture usage, but the build itself uses `ctypes` and does not link against libpcap at package time.
