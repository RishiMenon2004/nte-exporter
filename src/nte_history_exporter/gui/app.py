from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

from nte_history_exporter.constants import EXPORTER_VERSION
from nte_history_exporter.decoder.server_region import SERVER_REGIONS
from nte_history_exporter.gui import self_update, theme, trackers
from nte_history_exporter.gui.reporter import GuiReporter, PromptReply
from nte_history_exporter.live_capture.libpcap import LibpcapUnavailable
from nte_history_exporter.live_capture.runner import run_live_capture
from nte_history_exporter.update_check import ReleaseAsset, UpdateInfo, check_for_update

EXPORT_DIR = Path("exports")
WEB_DIR = Path(__file__).resolve().parent / "web"
BACKENDS = ("auto", "libpcap", "raw")
SMOKE_TIMEOUT_SECONDS = 60
# webbrowser.open returns before the browser has come forward, so the exports
# folder waits this long; opened any sooner it would end up behind the browser.
BROWSER_SETTLE_SECONDS = 0.6
# Lists the folder behind every open Explorer window and tab, one per line.
LIST_OPEN_FOLDERS_SCRIPT = (
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8;"
    "(New-Object -ComObject Shell.Application).Windows() | ForEach-Object {"
    " try { $_.Document.Folder.Self.Path } catch {} }"
)

TEXT = theme.TEXT


def drop_plaintext(payloads: list[str], skip_banners: tuple[str, ...] = ()) -> str | None:
    """Group a capture's exports into the document a tracker import drop carries.

    Returns None if the site takes none of them.
    """
    exports = [json.loads(payload) for payload in payloads]
    exports = [export for export in exports if export["banner"]["id"] not in skip_banners]
    if not exports:
        return None
    return json.dumps({"version": 1, "exports": exports}, ensure_ascii=False, separators=(",", ":"))


def format_pages(pages: set[int]) -> str:
    """Collapse page numbers into ranges, e.g. {1, 2, 3, 5} -> "1-3, 5"."""
    ranges: list[str] = []
    ordered = sorted(pages)
    start = prev = None
    for page in ordered + [None]:
        if start is not None and (page is None or page != prev + 1):
            ranges.append(str(start) if start == prev else f"{start}-{prev}")
            start = None
        if page is not None and start is None:
            start = page
        prev = page
    return ", ".join(ranges)


class Bridge:
    """The page's view of the app, exposed to JavaScript as ``pywebview.api``.

    Capture runs on a worker thread and reports through ``self.events``. The
    page calls ``poll()`` on a timer, which turns those events into render
    operations (plain dicts handled by the ``ops`` table in web/app.js), so all
    capture logic stays here. Pywebview runs each JavaScript call on its own
    thread, hence the lock. Names starting with ``_`` are hidden from the page.
    """

    def __init__(self) -> None:
        self.events: queue.Queue = queue.Queue()
        self._window = None
        self._lock = threading.RLock()
        self._ops: list[dict] = []
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._copy_after_capture = False
        self._close_when_done = False
        self._closing_confirmed = False
        self._payloads: list[str] = []  # Exports from the latest capture.
        self._rows: dict[str, dict] = {}
        self._pages: dict[str, set[int]] = {}
        self._prompts: dict[int, PromptReply] = {}
        self._next_prompt = 0
        self._update: UpdateInfo | None = None
        self._updating = False
        self._update_percent = -1
        self._ready = threading.Event()

    def _attach(self, window) -> None:
        self._window = window

    # ------------------------------------------------------- called by the page

    def bootstrap(self) -> dict:
        return {
            "text": TEXT,
            "version": EXPORTER_VERSION,
            "backends": BACKENDS,
            "trackers": [{"key": key, "label": site["label"]} for key, site in trackers.SITES.items()],
        }

    def ready(self) -> None:
        """The page has rendered; start the window-dependent work."""
        self._ready.set()
        use_dark_title_bar(self._window)
        threading.Thread(target=self._check_for_update, daemon=True).start()

    def poll(self) -> list[dict]:
        with self._lock:
            try:
                while True:
                    name, *args = self.events.get_nowait()
                    getattr(self, f"_on_{name}")(*args)
            except queue.Empty:
                pass
            ops, self._ops = self._ops, []
            return ops

    def start_capture(self, settings: dict) -> None:
        with self._lock:
            if self._capture_running() or self._updating:
                return
            self._rows.clear()
            self._pages.clear()
            self._payloads = []
            self._emit("reset")
            backend = settings.get("backend")
            options = {
                "interface_ip": (settings.get("interface_ip") or "").strip() or None,
                "capture_backend": backend if backend in BACKENDS else "auto",
                "write_debug_csv": bool(settings.get("debug")),
                "user_uid": (settings.get("user_uid") or "").strip() or None,
            }
            self._copy_after_capture = bool(settings.get("copy_clipboard"))
            self._stop_event.clear()
            self._worker = threading.Thread(target=self._run_capture, args=(options,), daemon=True)
            self._worker.start()
            self._emit("state", state="running")

    def stop_capture(self) -> None:
        with self._lock:
            self._request_stop()

    def answer_prompt(self, prompt_id: int, value: str | None) -> None:
        with self._lock:
            reply = self._prompts.pop(prompt_id, None)
        if reply is not None:
            reply.answer((value or "").strip() or None)

    def report_copy(self, copied: bool) -> None:
        with self._lock:
            self._append((TEXT["copied"] if copied else TEXT["copy_failed"], "success" if copied else "warning"))

    def open_exports(self) -> None:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = str(EXPORT_DIR.resolve())
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def open_update(self) -> None:
        """Install the update if this build can, or else show its release page."""
        with self._lock:
            if self._update is None or self._updating:
                return
            asset = self_update.find_asset(self._update)
            if asset is None:
                webbrowser.open(self._update.release_url)
            elif self._capture_running():
                self._append((TEXT["update_blocked"], "warning"))
            else:
                self._updating = True
                self._emit("update", text=TEXT["update_downloading"].format(percent=0), busy=True)
                threading.Thread(target=self._run_update, args=(asset,), daemon=True).start()

    def import_drop(self, key: str) -> dict | None:
        """What the page should encrypt and upload for this tracker, if anything."""
        drop = trackers.SITES.get(key, {}).get("drop")
        with self._lock:
            payloads = list(self._payloads)
        if not drop or not payloads:
            return None
        plaintext = drop_plaintext(payloads, drop.get("skip_banners", ()))
        if plaintext is None:
            return None
        return {"upload_url": drop["upload_url"], "plaintext": plaintext}

    def report_drop_failed(self, key: str, reason: str) -> None:
        site = trackers.SITES.get(key)
        if site:
            with self._lock:
                self._append((TEXT["drop_failed"].format(site=site["label"], reason=reason), "warning"))

    def open_tracker(self, key: str, fragment: str | None = None) -> None:
        """Open a tracker site: on an uploaded drop if there is one, or else
        with the exports folder alongside it, ready to drag from.

        ``fragment`` is the drop's "<dropId>.<key>". It goes after the # so that
        the decryption key is never sent to a server.
        """
        site = trackers.SITES.get(key)
        if not site:
            return
        if fragment and "drop" in site:
            webbrowser.open(f"{site['drop']['open_url']}#{fragment}")
            with self._lock:
                self._append((TEXT["drop_sent"].format(site=site["label"]), "success"))
            return
        folder_needed = not exports_folder_is_open()
        webbrowser.open(site["url"])
        if folder_needed:
            time.sleep(BROWSER_SETTLE_SECONDS)
            try:
                self.open_exports()
            except OSError:
                pass  # The site is open, which is the main thing.

    def resolve_close(self, choice: str) -> None:
        """Answer to the dialog raised by ``_on_window_closing``."""
        if choice == "save":
            with self._lock:
                self._close_when_done = True
                self._request_stop()
        elif choice == "discard":
            self._close_window()

    # ------------------------------------------------------------ capture flow

    def _capture_running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def _run_capture(self, options: dict) -> None:
        """Runs on the worker thread; reports back only through self.events."""
        try:
            result = run_live_capture(
                **options,
                reporter=GuiReporter(self.events),
                stop_requested=self._stop_event.is_set,
            )
        except (LibpcapUnavailable, PermissionError) as exc:
            self.events.put(("failed", str(exc), TEXT["capture_permission_hint"]))
        except Exception as exc:
            self.events.put(("failed", f"{type(exc).__name__}: {exc}", traceback.format_exc()))
        else:
            self.events.put(("finished", result))

    def _run_update(self, asset: ReleaseAsset) -> None:
        """Runs on a worker thread; reports back only through self.events."""
        target = self_update.current_install()
        try:
            downloaded = self_update.download(
                asset, target, lambda percent: self.events.put(("update_progress", percent))
            )
            self.events.put(("update_installing",))
            self_update.install(downloaded, target)
        except Exception as exc:
            self.events.put(("update_failed", str(exc) or type(exc).__name__))
        else:
            self._close_window()

    def _request_stop(self) -> None:
        self._stop_event.set()
        self._emit("state", state="stopping")
        self._emit("status", text=TEXT["status_saving"])

    def _on_window_closing(self) -> bool:
        """Pywebview close hook; returning False keeps the window open."""
        if self._closing_confirmed or not self._capture_running():
            return True
        with self._lock:
            if not self._close_when_done:
                self._emit(
                    "dialog",
                    kind="close",
                    title=TEXT["close_title"],
                    message=TEXT["close_while_running"],
                    buttons=[
                        {"label": TEXT["close_cancel"], "value": "cancel", "cancel": True},
                        {"label": TEXT["close_discard"], "value": "discard"},
                        {"label": TEXT["close_save"], "value": "save", "primary": True},
                    ],
                )
        return False

    def _close_window(self) -> None:
        self._closing_confirmed = True
        # destroy() waits for the UI thread, which may be serving this very call.
        threading.Thread(target=self._window.destroy, daemon=True).start()

    # ---------------------------------------------------------- event handlers

    def _on_log(self, text: str, tag: str) -> None:
        self._append((text, tag))

    def _on_listening(self, local_ip: str, backend: str, detail: str) -> None:
        self._append(("Listening on ", "muted"), (local_ip, "heading"))
        backend_detail = f" ({detail})" if detail and detail != local_ip else ""
        self._append((f"Capture backend: {backend}{backend_detail}", "muted"))
        self._append((TEXT["ready"], "success"))
        self._append(("", "info"))
        self._emit("status", text=TEXT["status_listening"].format(ip=local_ip, backend=backend))

    def _on_page(self, label: str, page: int | None, recaptured: bool) -> None:
        if page is not None:
            self._pages.setdefault(label, set()).add(page)
        action = "recaptured" if recaptured else "page"
        self._append(("+ ", "success"), (label, "info"), (f"  {action} {page}", "muted"))
        if self._rows.get(label, {}).get("tag") == "warning":
            self._set_row(label, None, None)
        else:
            self._set_row(label, "Receiving pages", "")

    def _on_missing(self, label: str, pages: list[int]) -> None:
        page_list = ", ".join(str(page) for page in pages)
        self._append((f"! {label} missing page(s): {page_list}.", "warning"))
        self._append((f"  {TEXT['gap_hint']}", "info"))
        self._set_row(label, f"Missing page(s) {page_list}", "warning")

    def _on_recovered(self, label: str) -> None:
        self._append((f"+ {label} page gap recovered.", "success"))
        self._set_row(label, "Gap recovered", "success")

    def _on_achievements(
        self, in_game_completed: int, in_game_in_progress: int, ps_completed: int, ps_in_progress: int
    ) -> None:
        self._append(("+ ", "success"), ("Achievements captured", "info"))
        self._append((f"    In-game      {in_game_completed} completed, {in_game_in_progress} in progress", "muted"))
        self._append((f"    PlayStation  {ps_completed} completed, {ps_in_progress} in progress", "muted"))
        self._set_row(
            TEXT["achievements_row"],
            f"{in_game_completed + ps_completed} completed, {in_game_in_progress + ps_in_progress} in progress",
            "success",
        )

    def _on_results(self) -> None:
        self._append(("", "info"))
        self._append(("Results", "heading"))

    def _on_summary(self, name: str, decoded: int, exported: int, skipped: int) -> None:
        self._append(
            (f"{name:<30}", "info"),
            (f"decoded {decoded}   ", "muted"),
            (f"exported {exported}   ", "success"),
            (f"skipped {skipped}", "warning" if skipped else "muted"),
        )

    def _on_prompt(self, kind: str, reply: PromptReply) -> None:
        self._next_prompt += 1
        self._prompts[self._next_prompt] = reply
        if kind == "user_uid":
            title, message, choices = TEXT["uid_prompt_title"], TEXT["uid_prompt"], None
        else:
            title, message = TEXT["server_prompt_title"], TEXT["server_prompt"]
            choices = [(server_id, details["name"]) for server_id, details in SERVER_REGIONS.items()]
        self._emit(
            "dialog",
            kind="prompt",
            id=self._next_prompt,
            title=title,
            message=message,
            choices=choices,
            buttons=[
                {"label": TEXT["skip"], "value": "skip", "cancel": True},
                {"label": TEXT["ok"], "value": "submit", "primary": True},
            ],
        )

    def _on_finished(self, result: dict) -> None:
        self._emit("state", state="idle")
        exports = result["exports"]
        self._payloads = [export["payload"] for export in exports]
        if self._copy_after_capture and len(exports) == 1:
            # Written by the page; report_copy() logs how that went.
            self._emit("copy", text=exports[0]["payload"])
        elif self._copy_after_capture and len(exports) > 1:
            self._append((TEXT["copy_skipped"], "muted"))
        saved = len(exports) + (result["achievement_path"] is not None)
        self._emit("status", text=TEXT["status_done"].format(count=saved))
        if self._close_when_done:
            self._close_window()

    def _on_failed(self, message: str, detail: str) -> None:
        self._emit("state", state="idle")
        self._append((message, "error"))
        self._append((detail, "muted"))
        self._emit("status", text=TEXT["status_failed"])
        if self._close_when_done:
            self._close_window()
            return
        self._emit(
            "dialog",
            kind="alert",
            title=TEXT["capture_failed_title"],
            message=message,
            buttons=[{"label": TEXT["dismiss"], "value": "dismiss", "primary": True, "cancel": True}],
        )

    def _on_update(self, update: UpdateInfo) -> None:
        self._update = update
        self._emit("update", text=self._update_label(), busy=False)

    def _on_update_progress(self, percent: int) -> None:
        if percent != self._update_percent:
            self._update_percent = percent
            self._emit("update", text=TEXT["update_downloading"].format(percent=percent), busy=True)

    def _on_update_installing(self) -> None:
        self._emit("update", text=TEXT["update_installing"], busy=True)

    def _on_update_failed(self, reason: str) -> None:
        self._updating = False
        self._update_percent = -1
        self._append((TEXT["update_failed"].format(reason=reason), "warning"))
        self._emit("update", text=self._update_label(), busy=False)
        webbrowser.open(self._update.release_url)

    # ----------------------------------------------------------------- helpers

    def _update_label(self) -> str:
        key = "update_install" if self_update.find_asset(self._update) else "update_available"
        return TEXT[key].format(version=self._update.latest_version)

    def _emit(self, op: str, **fields) -> None:
        self._ops.append({"op": op, **fields})

    def _append(self, *segments: tuple[str, str]) -> None:
        self._emit("log", segments=segments)

    def _set_row(self, label: str, status: str | None, tag: str | None) -> None:
        """Insert or update a captured-list row; None keeps the current status/tag."""
        row = self._rows.setdefault(label, {"status": "", "tag": ""})
        if status is not None:
            row["status"] = status
        if tag is not None:
            row["tag"] = tag
        self._emit("row", label=label, pages=format_pages(self._pages.get(label, set())), **row)

    def _check_for_update(self) -> None:
        update = check_for_update(EXPORTER_VERSION)
        if update:
            self.events.put(("update", update))


def open_explorer_folders() -> list[str]:
    """Folders open in Windows Explorer; empty elsewhere or if Explorer can't be asked."""
    if sys.platform != "win32":
        return []
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", LIST_OPEN_FOLDERS_SCRIPT],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def exports_folder_is_open() -> bool:
    target = os.path.normcase(os.path.normpath(EXPORT_DIR.resolve()))
    return any(os.path.normcase(os.path.normpath(folder)) == target for folder in open_explorer_folders())


def use_dark_title_bar(window) -> None:
    """Ask Windows 10/11 for a dark title bar to match the page; a no-op elsewhere."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = window.native.Handle.ToInt32()
        value = ctypes.c_int(1)
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        pass


def _create_window(webview, bridge: Bridge, hidden: bool = False):
    window = webview.create_window(
        TEXT["window_title"],
        url=str(WEB_DIR / "index.html"),
        js_api=bridge,
        width=theme.WINDOW["size"][0],
        height=theme.WINDOW["size"][1],
        min_size=theme.WINDOW["min_size"],
        background_color=theme.WINDOW["background"],
        text_select=True,
        hidden=hidden,
    )
    bridge._attach(window)
    window.events.closing += bridge._on_window_closing
    return window


def _start_options() -> dict:
    # A local http server gives the page a secure context for the clipboard API.
    # Windows must not fall back to the legacy MSHTML engine, which cannot render the page.
    options: dict = {"http_server": True}
    if sys.platform == "win32":
        options["gui"] = "edgechromium"
    return options


def _show_startup_error(error: Exception) -> None:
    """A windowed build has no console, so report a failed start with a native dialog."""
    message = TEXT["webview_missing"].format(error=error)
    print(message, file=sys.stderr)
    if sys.platform == "win32":
        import ctypes

        MB_ICONERROR = 0x10
        ctypes.windll.user32.MessageBoxW(None, message, TEXT["window_title"], MB_ICONERROR)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--smoke-test" in args:
        return _smoke_test()
    _use_writable_working_dir()
    threading.Thread(target=self_update.remove_leftovers, daemon=True).start()
    try:
        import webview

        _create_window(webview, Bridge())
        webview.start(**_start_options())
    except Exception as exc:
        _show_startup_error(exc)
        return 1
    return 0


def _use_writable_working_dir() -> None:
    """Move to a folder the user can find, since exports/ is relative to the working directory.

    A macOS .app is started in "/", and a file manager may start a binary in a
    read-only folder; on Windows a double-clicked exe starts next to itself and
    stays there.
    """
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        target = Path.home() / "Documents" / "NTE History Exporter"
    elif os.access(Path.cwd(), os.W_OK):
        return
    else:
        target = Path.home() / "NTE History Exporter"
    try:
        target.mkdir(parents=True, exist_ok=True)
        os.chdir(target)
    except OSError:
        pass


def _smoke_test() -> int:
    """Load the whole page in a hidden window and exit; used by CI to check packaged builds.

    Passes only if the page's script reached the bridge, which proves the
    webview, the bundled web files and the JavaScript link all work. A windowed
    build has no console and shows a blocking dialog on an uncaught error, so
    failures are turned into exit code 1 instead.
    """
    try:
        import webview

        bridge = Bridge()
        window = _create_window(webview, bridge, hidden=True)
        outcome: list[bool] = []

        def wait_for_page() -> None:
            outcome.append(bridge._ready.wait(SMOKE_TIMEOUT_SECONDS))
            window.destroy()

        webview.start(wait_for_page, **_start_options())
        return 0 if outcome == [True] else 1
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
