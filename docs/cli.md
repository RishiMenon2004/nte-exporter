# Command-line usage

The command-line exporter does the same live capture as the desktop GUI, in a
terminal. It also replays saved captures for research and testing.

<div align="center">
  <img src="images/cli-demo.png" width="480" alt="Live capture session: instructions, captured pages, and the results summary" />
</div>

## Requirements

- Python 3.10 or newer when running from source. Release binaries include the Python runtime.
- Packet-capture permission. On Windows, Npcap can usually capture without running this tool as Administrator; the raw-socket fallback may need Administrator. On Linux and macOS, use root or capture capabilities as required by your system.
- **Windows:** [Npcap](https://npcap.com/) is recommended. Install it normally; WinPcap API-compatible mode is not required. If Npcap is unavailable or cannot be initialized, `auto` falls back to the Windows built-in raw-socket backend.
- **Linux:** install the system **libpcap** runtime if it is not already present. Package names commonly include `libpcap0.8` on Debian/Ubuntu and `libpcap` on Fedora, Arch, and similar distributions.
- **macOS:** the system normally includes **libpcap**, so no separate Npcap installation is needed.

Npcap is Windows-only and is not bundled with this project. Linux and macOS use libpcap, the cross-platform capture library on which Npcap is based.

## Downloads

The [Releases page](https://github.com/RishiMenon2004/nte-exporter/releases) has
a command-line build for each platform:

| Platform | File |
| -------- | ---- |
| Windows | `nte-history-exporter.exe` |
| Linux | `nte-history-exporter-linux` |
| macOS | `nte-history-exporter-macos` |

Each platform also has a versioned `nte-history-exporter-v<version>-….zip`. The
Windows and Linux zips contain both the command-line and GUI builds.

## Live capture

> [!IMPORTANT]
> Start the exporter **before pressing Start on the game's main menu**. This is
> required for achievement capture and enables automatic user UID and
> account-server detection. If already in game, pull-history capture still
> works, but achievements require returning to the main menu and logging in
> again; missing account details are requested before saving.

### Windows

The Windows executable is a console app. Start it from a terminal:

```powershell
.\nte-history-exporter.exe
```

From source, run `.\run-exporter.ps1`, or double-click **`run-exporter.cmd`**.

### Linux and macOS

Make the downloaded binary executable before running it. Use `sudo` only when
your system requires elevated capture permission:

```bash
chmod +x ./nte-history-exporter-linux
sudo ./nte-history-exporter-linux
```

Use `nte-history-exporter-macos` in the same way on macOS. If your browser or OS
blocks a downloaded macOS binary, allow it from the system security prompt before
running it again.

From source, install the project and ensure the system libpcap runtime is available:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
sudo .venv/bin/nte-history-exporter
```

Capture can also be granted through platform-specific capabilities instead of
running the whole exporter with `sudo`.

### During a capture

Once running, open any supported history board in game. The tool keeps listening
until you press any key. After it prints and saves the results, press any key
again to close the exporter. Exports are written under `exports\` as:

- `<user_uid>_Permanent_<date_time>.json`
- `<user_uid>_Limited_<date_time>.json`
- `<user_uid>_Arc_<date_time>.json`
- `<user_uid>_MysteryBox_<date_time>.json`
- `<user_uid>_Achievements_<date_time>.json`

If the user UID is not detected automatically, the console asks for it before
saving. Leaving it blank saves as `unknown_<banner>_<date_time>.json`, but may
prevent import on some trackers.

The export also includes `server_id` and `account_region` when known. If the
initial TCP server-selection response was missed, the console offers Asia,
America, Europe, and SEA as a numbered choice. The prompt can be left blank to
omit server information.

Exports are not copied to the clipboard by default. Add `--copy-clipboard` to
copy a single captured banner's JSON after saving. If multiple banners are
captured in the same run, clipboard copy is skipped so one banner does not
overwrite another.

If a page response is missed, the exporter reports the missing page number while
capture is still running. Leave the exporter open, close and reopen that history
board, then scroll down again. Scrolling backward within the existing view does
not request the cached pages again. The replacement capture is accepted and the
tool confirms when the gap has been recovered. If reopening the board still
produces no page messages, return to the main menu and re-enter the game to start
a fresh connection.

> [!TIP]
> For reliable deduplication, start from page 1 and scroll through the pages. If
> you only want pages 1–5, scroll through to page 6 as well just to be on the
> safe side.

### Achievements

The tracked achievement state is loaded during login, captured automatically, and
written to `exports/<user_uid>_Achievements_*.json` as a versioned achievement
export with account metadata, completion totals, and records grouped by
achievement category. Both completed and in-progress achievements are included
with their current progress, status, and completion time when available.
Generated metadata adds the localized title and description, target, quality, and
rewards from the current `NTE_Assets` achievement table. Newly captured IDs that
are not yet in the bundled mapping still export normally; only their optional
display metadata is omitted until the mappings are refreshed.

PlayStation trophy entries are retained and identified separately even though
they are not shown in the in-game achievement list. The console reports completed
and in-progress totals for in-game and PlayStation records as soon as the list
has been decoded. Every observed record without a completion timestamp is
classified as `in_progress`, even when its numeric progress is zero; compound
achievements can track hidden checklist progress this way.

## Options

| Flag      | Effect                                              |
| --------- | --------------------------------------------------- |
| `--live`  | Capture live traffic, including achievements loaded at login. |
| `--debug` | Also write the research CSV, privacy-safe capture diagnostics, and sanitized replay payloads. |
| `--user-uid <uid>` | Override the auto-detected NTE user UID in the JSON export. |
| `--copy-clipboard` | Copy a single live export JSON to clipboard after saving. |

The default `auto` capture backend uses Npcap on Windows when it's installed,
falling back to the built-in raw-socket backend, and the system libpcap library
on Linux and macOS. To choose one yourself:

```text
--capture-backend auto      Prefer Npcap/libpcap; fall back to raw sockets on Windows
--capture-backend libpcap   Require Npcap on Windows or libpcap on Linux/macOS
--capture-backend raw       Require the Windows raw-socket backend
```

The `--debug` flag writes three sidecars under `exports/`:

1. **Research CSV** (`<uid>_<banner>_<timestamp>.csv`): decoded research fields and raw captured records.
2. **Capture diagnostics** (`Capture_*.diagnostics.json`): shareable reason codes and packet counts without payloads, network addresses, ports, timestamps, or user UIDs.
3. **Sanitized replay payloads** (`Capture_*.payloads.json`): sanitized UDP packet payloads scrubbed of real IPs, ports, and user UIDs, ready for offline debugging and regression tests with `tools/replay_payloads.py`. See [Capture diagnostics](capture-diagnostics.md).

## File replay and offline research

### mitmproxy flows

Decode a `mitmproxy .flows` capture instead of listening live, for research and
testing:

```powershell
.\nte-history-exporter.exe capture.flows
```

From source, use `.\run-exporter.ps1 capture.flows`.

### Captured UDP payloads

Replay any sanitized UDP payload capture (`Capture_*.payloads.json` or
`capture.json`) through the decoder offline without running the game:

```powershell
python tools/replay_payloads.py exports/Capture_*.payloads.json [--debug]
```

You can also record raw UDP history traffic directly into a replayable JSON file:

```powershell
python tools/capture_payloads.py [--out exports/capture.json]
```

## Capture sources

**Current**

- Live Npcap/libpcap capture on Windows, Linux, and macOS
- Live Windows raw-socket fallback
- Sanitized UDP payload capture and offline replay (`tools/capture_payloads.py`, `tools/replay_payloads.py`)
- `mitmproxy .flows` research decoder

**Planned**

- Optional pktmon diagnostics for capture-drop investigation
