from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import Callable

from nte_history_exporter.constants import EXPORTER_VERSION, GAME_NAME
from nte_history_exporter.decoder.server_region import SERVER_REGIONS
from nte_history_exporter.gui import theme
from nte_history_exporter.gui.reporter import GuiReporter, PromptReply
from nte_history_exporter.live_capture.libpcap import LibpcapUnavailable
from nte_history_exporter.live_capture.runner import run_live_capture
from nte_history_exporter.update_check import check_for_update

EXPORT_DIR = Path("exports")
# Per-user GUI preferences (currently just the chosen palette).
PREFS_PATH = Path(os.environ.get("APPDATA") or Path.home() / ".config") / "nte-history-exporter" / "gui.json"
BACKENDS = ("auto", "libpcap", "raw")
POLL_MS = 50

TEXT = theme.TEXT


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


class ExporterApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.palette = load_palette()
        self.colors = theme.PALETTES[self.palette]
        # Tk scales fonts to the display DPI but not pixel sizes, so every size
        # from theme.py goes through px() to keep proportions on scaled displays.
        # macOS reports 72 DPI, which would shrink everything; never scale below 1.
        self.scale = max(1.0, root.winfo_fpixels("1i") / 96)
        self.events: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.copy_after_capture = False
        self.close_when_done = False
        self.rows: dict[str, str] = {}
        self.pages: dict[str, set[int]] = {}

        self.backend = tk.StringVar(value="auto")
        self.interface_ip = tk.StringVar()
        self.user_uid = tk.StringVar()
        self.copy_clipboard = tk.BooleanVar(value=True)
        self.debug = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value=TEXT["status_idle"])

        self._configure_window()
        self._build_layout()
        self._apply_palette()
        self._show_instructions()

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(POLL_MS, self._drain_events)
        threading.Thread(target=self._check_for_update, daemon=True).start()

    # ------------------------------------------------------------------ setup

    def px(self, value: float) -> int:
        return round(value * self.scale)

    def _configure_window(self) -> None:
        self.root.title(TEXT["window_title"])
        width, height = theme.WINDOW["size"]
        self.root.geometry(f"{self.px(width)}x{self.px(height)}")
        self.root.minsize(*(self.px(size) for size in theme.WINDOW["min_size"]))

    @property
    def dark(self) -> bool:
        return self.palette == theme.DARK_PALETTE

    def _apply_palette(self) -> None:
        """Color every widget from self.colors; runs at startup and on each theme toggle."""
        c = self.colors
        self.root.configure(bg=c["bg"])
        self._configure_styles()
        # Plain Tk widgets ignore ttk styles, so they are recolored directly.
        self.log.configure(
            background=c["field"], foreground=c["text"], insertbackground=c["text"], selectbackground=c["select"]
        )
        for tag, color_key in theme.LOG_COLORS.items():
            self.log.tag_configure(tag, foreground=c[color_key])
        for tag in ("success", "warning", "error"):
            self.tree.tag_configure(tag, foreground=c[tag])
        # The combobox dropdown is a Tk listbox inside a hidden popdown window.
        popdown = self.root.tk.call("ttk::combobox::PopdownWindow", self.backend_box)
        self.root.tk.call(
            f"{popdown}.f.l",
            "configure",
            "-background", c["field"],
            "-foreground", c["text"],
            "-selectbackground", c["select"],
            "-selectforeground", c["text"],
            "-font", theme.FONTS["body"],
        )
        family, glyph = self._theme_icon("to_light" if self.dark else "to_dark")
        ttk.Style(self.root).configure("Toggle.TButton", font=(family, theme.THEME_ICON_SIZE))
        self.theme_button.configure(text=glyph)
        set_title_bar_theme(self.root, self.dark)

    def _theme_icon(self, name: str) -> tuple[str, str]:
        """The first (font, glyph) in theme.THEME_ICONS[name] whose font is installed."""
        installed = set(tkfont.families(self.root))
        for family, glyph in theme.THEME_ICONS[name]:
            if family is None or family in installed:
                return family or theme.FONT_FAMILY, glyph
        return theme.FONT_FAMILY, theme.THEME_ICONS[name][-1][1]

    def _toggle_theme(self) -> None:
        self.palette = theme.LIGHT_PALETTE if self.dark else theme.DARK_PALETTE
        self.colors = theme.PALETTES[self.palette]
        self._apply_palette()
        save_palette(self.palette)

    def _configure_styles(self) -> None:
        c, f = self.colors, theme.FONTS
        style = ttk.Style(self.root)
        # "clam" is the built-in theme that honours custom colors on every platform.
        style.theme_use("clam")

        style.configure(
            ".",
            background=c["bg"],
            foreground=c["text"],
            font=f["body"],
            bordercolor=c["border"],
            lightcolor=c["surface"],
            darkcolor=c["surface"],
            troughcolor=c["field"],
            fieldbackground=c["field"],
            insertcolor=c["text"],
            selectbackground=c["select"],
            selectforeground=c["text"],
            focuscolor=c["accent"],
        )
        style.configure("TFrame", background=c["bg"])
        style.configure("Card.TFrame", background=c["surface"])

        style.configure("TLabel", background=c["bg"], foreground=c["text"])
        style.configure("Title.TLabel", font=f["title"])
        style.configure("Subtitle.TLabel", font=f["subtitle"], foreground=c["muted"])
        style.configure("Heart.TLabel", font=f["subtitle"], foreground=c["error"])
        style.configure("Link.TLabel", font=f["heading"], foreground=c["warning"])
        style.configure("Card.TLabel", background=c["surface"])
        style.configure("Heading.Card.TLabel", font=f["heading"])
        style.configure("Hint.Card.TLabel", font=f["hint"], foreground=c["muted"])
        style.configure("Muted.Card.TLabel", foreground=c["muted"])
        style.configure(
            "Status.TLabel", background=c["surface"], foreground=c["muted"], padding=(self.px(16), self.px(6))
        )

        for widget in ("TCheckbutton", "TRadiobutton"):
            style.configure(
                widget,
                background=c["surface"],
                foreground=c["text"],
                indicatorbackground=c["field"],
                indicatorforeground=c["accent_text"],
                indicatorsize=self.px(14),
                indicatormargin=(0, 0, self.px(8), 0),
                upperbordercolor=c["border"],
                lowerbordercolor=c["border"],
            )
            style.map(
                widget,
                background=[("active", c["surface"])],
                foreground=[("disabled", c["muted"])],
                indicatorbackground=[
                    ("disabled", c["surface_alt"]),
                    ("selected", c["accent"]),
                    ("pressed", c["accent_hover"]),
                ],
            )
        # Radio buttons read better as an accent dot on the field than as a filled circle.
        style.configure("TRadiobutton", indicatorforeground=c["accent"])
        style.map(
            "TRadiobutton",
            indicatorbackground=[("disabled", c["surface_alt"]), ("pressed", c["surface_alt"])],
            upperbordercolor=[("selected", c["accent"])],
            lowerbordercolor=[("selected", c["accent"])],
        )

        style.configure("TEntry", foreground=c["text"], padding=self.px(5))
        style.map(
            "TEntry",
            bordercolor=[("focus", c["accent"])],
            lightcolor=[("focus", c["accent"])],
            fieldbackground=[("disabled", c["surface_alt"])],
            foreground=[("disabled", c["muted"])],
        )
        style.configure("TCombobox", background=c["surface_alt"], arrowcolor=c["text"], padding=self.px(5))
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", c["field"]), ("disabled", c["surface_alt"])],
            foreground=[("disabled", c["muted"])],
            selectbackground=[("readonly", c["field"])],
            selectforeground=[("readonly", c["text"])],
            bordercolor=[("focus", c["accent"])],
            arrowcolor=[("disabled", c["muted"])],
        )

        style.configure(
            "TButton",
            background=c["surface_alt"],
            foreground=c["text"],
            padding=(self.px(14), self.px(8)),
            borderwidth=0,
            lightcolor=c["surface_alt"],
            darkcolor=c["surface_alt"],
        )
        style.map("TButton", background=[("active", c["border"]), ("disabled", c["surface_alt"])])
        style.configure(
            "Toggle.TButton",
            background=c["bg"],
            foreground=c["muted"],
            lightcolor=c["bg"],
            darkcolor=c["bg"],
            padding=self.px(8),
            width=0,  # clam gives buttons an 11-character minimum width; size to the icon instead
        )
        style.map(
            "Toggle.TButton",
            background=[("active", c["surface_alt"])],
            foreground=[("active", c["text"])],
            lightcolor=[("active", c["surface_alt"])],
            darkcolor=[("active", c["surface_alt"])],
        )
        for name, color, hover in (
            ("Accent.TButton", c["accent"], c["accent_hover"]),
            ("Danger.TButton", c["error"], c["error_hover"]),
        ):
            style.configure(
                name,
                background=color,
                foreground=c["accent_text"],
                font=f["heading"],
                lightcolor=color,
                darkcolor=color,
            )
            style.map(
                name,
                background=[("disabled", c["surface_alt"]), ("active", hover)],
                foreground=[("disabled", c["muted"])],
                lightcolor=[("disabled", c["surface_alt"]), ("active", hover)],
                darkcolor=[("disabled", c["surface_alt"]), ("active", hover)],
            )

        style.configure(
            "Treeview",
            background=c["field"],
            fieldbackground=c["field"],
            foreground=c["text"],
            rowheight=self.px(theme.LAYOUT["row_height"]),
            borderwidth=0,
        )
        style.map("Treeview", background=[("selected", c["select"])], foreground=[("selected", c["text"])])
        style.configure(
            "Treeview.Heading",
            background=c["surface_alt"],
            foreground=c["muted"],
            font=f["heading"],
            relief="flat",
            padding=(self.px(8), self.px(4)),
        )
        style.map("Treeview.Heading", background=[("active", c["surface_alt"])])
        style.configure(
            "Vertical.TScrollbar",
            background=c["surface_alt"],
            troughcolor=c["field"],
            arrowcolor=c["muted"],
            bordercolor=c["field"],
            lightcolor=c["surface_alt"],
            darkcolor=c["surface_alt"],
            gripcount=0,
            arrowsize=self.px(12),
        )
        # clam's defaults paint a light-grey thumb when disabled (nothing to scroll) or hovered.
        style.map(
            "Vertical.TScrollbar",
            background=[("disabled", c["surface_alt"]), ("active", c["border"])],
            lightcolor=[("disabled", c["surface_alt"]), ("active", c["border"])],
            darkcolor=[("disabled", c["surface_alt"]), ("active", c["border"])],
        )
        style.configure("TSeparator", background=c["border"])

    def _build_layout(self) -> None:
        pad, gap = self.px(theme.LAYOUT["padding"]), self.px(theme.LAYOUT["gap"])

        ttk.Label(self.root, textvariable=self.status, style="Status.TLabel", anchor="w").pack(
            side="bottom", fill="x"
        )
        outer = ttk.Frame(self.root, padding=pad)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")
        title_row = ttk.Frame(header)
        title_row.pack(fill="x")
        ttk.Label(title_row, text=TEXT["title"], style="Title.TLabel").pack(side="left")
        ttk.Label(title_row, text=f"v{EXPORTER_VERSION}", style="Subtitle.TLabel").pack(
            side="left", padx=(self.px(8), 0), pady=(self.px(6), 0)
        )
        self.theme_button = ttk.Button(title_row, style="Toggle.TButton", command=self._toggle_theme)
        self.theme_button.pack(side="right")
        Tooltip(self, self.theme_button, lambda: TEXT["theme_to_light"] if self.dark else TEXT["theme_to_dark"])
        self.update_label = ttk.Label(title_row, style="Link.TLabel", cursor="hand2")
        self.update_label.pack(side="right", padx=(0, self.px(12)))
        subtitle_row = ttk.Frame(header)
        subtitle_row.pack(anchor="w")
        for text, label_style in (
            (TEXT["subtitle"].format(game=GAME_NAME), "Subtitle.TLabel"),
            (TEXT["credit_before"], "Subtitle.TLabel"),
            ("♥", "Heart.TLabel"),
            (TEXT["credit_after"], "Subtitle.TLabel"),
        ):
            ttk.Label(subtitle_row, text=text, style=label_style).pack(side="left")

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True, pady=(gap, 0))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_sidebar(body).grid(row=0, column=0, sticky="ns", padx=(0, gap))

        main = ttk.Frame(body)
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=2)
        main.rowconfigure(1, weight=3)
        self._build_captured(main).grid(row=0, column=0, sticky="nsew", pady=(0, gap))
        self._build_activity(main).grid(row=1, column=0, sticky="nsew")

    def _build_sidebar(self, parent: tk.Misc) -> ttk.Frame:
        pad = self.px(theme.LAYOUT["padding"])
        wrap = self.px(theme.LAYOUT["sidebar_width"])
        card = ttk.Frame(parent, style="Card.TFrame", padding=pad)

        ttk.Label(card, text=TEXT["settings"], style="Heading.Card.TLabel").pack(anchor="w", pady=(0, self.px(8)))

        backend = ttk.Combobox(card, textvariable=self.backend, values=BACKENDS, state="readonly")
        self.backend_box = backend
        interface_ip = ttk.Entry(card, textvariable=self.interface_ip)
        user_uid = ttk.Entry(card, textvariable=self.user_uid)
        for label, widget, hint in (
            (TEXT["backend"], backend, TEXT["backend_hint"]),
            (TEXT["interface_ip"], interface_ip, TEXT["interface_ip_hint"]),
            (TEXT["user_uid"], user_uid, TEXT["user_uid_hint"]),
        ):
            ttk.Label(card, text=label, style="Card.TLabel").pack(anchor="w")
            widget.pack(fill="x", pady=(self.px(2), 0))
            ttk.Label(card, text=hint, style="Hint.Card.TLabel", wraplength=wrap).pack(anchor="w", pady=(self.px(1), self.px(8)))

        copy_clipboard = ttk.Checkbutton(card, text=TEXT["copy_clipboard"], variable=self.copy_clipboard)
        debug = ttk.Checkbutton(card, text=TEXT["debug"], variable=self.debug)
        copy_clipboard.pack(anchor="w")
        debug.pack(anchor="w", pady=(self.px(4), 0))
        self.setting_widgets = [backend, interface_ip, user_uid, copy_clipboard, debug]

        self.start_button = ttk.Button(
            card, text=TEXT["start"], style="Accent.TButton", command=self._toggle_capture
        )
        self.start_button.pack(fill="x", pady=(pad, self.px(6)))
        ttk.Button(card, text=TEXT["open_exports"], command=self._open_exports).pack(fill="x")
        return card

    def _build_captured(self, parent: tk.Misc) -> ttk.Frame:
        pad = self.px(theme.LAYOUT["padding"])
        card = ttk.Frame(parent, style="Card.TFrame", padding=pad)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)
        ttk.Label(card, text=TEXT["captured"], style="Heading.Card.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, self.px(8))
        )

        columns = ("banner", "pages", "status")
        self.tree = ttk.Treeview(card, columns=columns, show="headings", selectmode="none", height=4)
        for column, heading, width, stretch in (
            ("banner", TEXT["col_banner"], 220, True),
            ("pages", TEXT["col_pages"], 160, True),
            ("status", TEXT["col_status"], 220, True),
        ):
            self.tree.heading(column, text=heading, anchor="w")
            self.tree.column(column, width=self.px(width), stretch=stretch, anchor="w")
        scrollbar = ttk.Scrollbar(card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        return card

    def _build_activity(self, parent: tk.Misc) -> ttk.Frame:
        pad = self.px(theme.LAYOUT["padding"])
        card = ttk.Frame(parent, style="Card.TFrame", padding=pad)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(1, weight=1)
        ttk.Label(card, text=TEXT["activity"], style="Heading.Card.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, self.px(8))
        )

        self.log = tk.Text(
            card,
            wrap="word",
            state="disabled",
            font=theme.FONTS["log"],
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            padx=self.px(10),
            pady=self.px(8),
            height=8,
        )
        self.log.tag_configure("heading", font=(*theme.FONTS["log"][:2], "bold"))
        scrollbar = ttk.Scrollbar(card, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        return card

    # ------------------------------------------------------------ capture flow

    def _capture_running(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def _toggle_capture(self) -> None:
        if self._capture_running():
            self._request_stop()
        else:
            self._start_capture()

    def _start_capture(self) -> None:
        self.rows.clear()
        self.pages.clear()
        self.tree.delete(*self.tree.get_children())
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

        options = {
            "interface_ip": self.interface_ip.get().strip() or None,
            "capture_backend": self.backend.get(),
            "write_debug_csv": self.debug.get(),
            "user_uid": self.user_uid.get().strip() or None,
        }
        # Clipboard writes must happen on the Tk thread, so the copy is done here
        # after the capture finishes instead of inside the runner.
        self.copy_after_capture = self.copy_clipboard.get()
        self.stop_event.clear()
        self.worker = threading.Thread(target=self._run_capture, args=(options,), daemon=True)
        self.worker.start()
        self._set_running(True)

    def _run_capture(self, options: dict) -> None:
        """Runs on the worker thread; reports back only through self.events."""
        try:
            result = run_live_capture(
                **options,
                reporter=GuiReporter(self.events),
                stop_requested=self.stop_event.is_set,
            )
        except (LibpcapUnavailable, PermissionError) as exc:
            self.events.put(("failed", str(exc), TEXT["capture_permission_hint"]))
        except Exception as exc:
            self.events.put(("failed", f"{type(exc).__name__}: {exc}", traceback.format_exc()))
        else:
            self.events.put(("finished", result))

    def _request_stop(self) -> None:
        self.stop_event.set()
        self.start_button.configure(text=TEXT["stopping"], state="disabled")
        self.status.set(TEXT["status_saving"])

    def _set_running(self, running: bool) -> None:
        if running:
            self.start_button.configure(text=TEXT["stop"], style="Danger.TButton", state="normal")
        else:
            self.start_button.configure(text=TEXT["start"], style="Accent.TButton", state="normal")
        for widget in self.setting_widgets:
            if isinstance(widget, ttk.Combobox):
                widget.configure(state="disabled" if running else "readonly")
            else:
                widget.configure(state="disabled" if running else "normal")

    def _drain_events(self) -> None:
        try:
            while True:
                name, *args = self.events.get_nowait()
                getattr(self, f"_on_{name}")(*args)
        except queue.Empty:
            pass
        if self.root.winfo_exists():
            self.root.after(POLL_MS, self._drain_events)

    # ---------------------------------------------------------- event handlers

    def _on_log(self, text: str, tag: str) -> None:
        self._append((text, tag))

    def _on_listening(self, local_ip: str, backend: str, detail: str) -> None:
        self._append(("Listening on ", "muted"), (local_ip, "heading"))
        backend_detail = f" ({detail})" if detail and detail != local_ip else ""
        self._append((f"Capture backend: {backend}{backend_detail}", "muted"))
        self._append((TEXT["ready"], "success"))
        self._append(("", "info"))
        self.status.set(TEXT["status_listening"].format(ip=local_ip, backend=backend))

    def _on_page(self, label: str, page: int | None, recaptured: bool) -> None:
        if page is not None:
            self.pages.setdefault(label, set()).add(page)
        action = "recaptured" if recaptured else "page"
        self._append(("+ ", "success"), (label, "info"), (f"  {action} {page}", "muted"))
        if label not in self.rows or not self._row_has_tag(label, "warning"):
            self._set_row(label, "Receiving pages", "")
        else:
            self._set_row(label, None, None)

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
        if kind == "user_uid":
            dialog = PromptDialog(self, TEXT["uid_prompt_title"], TEXT["uid_prompt"])
        else:
            choices = [(server_id, details["name"]) for server_id, details in SERVER_REGIONS.items()]
            dialog = PromptDialog(self, TEXT["server_prompt_title"], TEXT["server_prompt"], choices)
        reply.answer(dialog.result)

    def _on_finished(self, result: dict) -> None:
        self._set_running(False)
        exports = result["exports"]
        if self.copy_after_capture and len(exports) == 1:
            self.root.clipboard_clear()
            self.root.clipboard_append(exports[0]["payload"])
            self._append((TEXT["copied"], "success"))
        elif self.copy_after_capture and len(exports) > 1:
            self._append((TEXT["copy_skipped"], "muted"))
        saved = len(exports) + (result["achievement_path"] is not None)
        self.status.set(TEXT["status_done"].format(count=saved))
        if self.close_when_done:
            self.root.destroy()

    def _on_failed(self, message: str, detail: str) -> None:
        self._set_running(False)
        self._append((message, "error"))
        self._append((detail, "muted"))
        self.status.set(TEXT["status_failed"])
        if self.close_when_done:
            self.root.destroy()
            return
        messagebox.showerror(TEXT["capture_failed_title"], message, parent=self.root)

    def _on_update(self, latest_version: str, release_url: str) -> None:
        self.update_label.configure(text=TEXT["update_available"].format(version=latest_version))
        self.update_label.bind("<Button-1>", lambda _event: webbrowser.open(release_url))

    # ----------------------------------------------------------------- helpers

    def _show_instructions(self) -> None:
        """Fill the idle activity log with the capture steps; cleared when a capture starts."""
        self._append((TEXT["how_to"], "heading"))
        self._append(("", "info"))
        for number, step in enumerate(TEXT["instructions"], start=1):
            self._append((f"{number}. ", "accent"), (step, "info"))
            self._append(("", "info"))

    def _append(self, *segments: tuple[str, str]) -> None:
        self.log.configure(state="normal")
        for text, tag in segments:
            self.log.insert("end", text, tag)
        self.log.insert("end", "\n")
        self.log.configure(state="disabled")
        self.log.see("end")

    def _row_has_tag(self, label: str, tag: str) -> bool:
        return tag in self.tree.item(self.rows[label], "tags")

    def _set_row(self, label: str, status: str | None, tag: str | None) -> None:
        """Insert or update a captured-list row; None keeps the current status/tag."""
        item = self.rows.get(label)
        if item is not None:
            _, _, current_status = self.tree.item(item, "values")
            current_tags = self.tree.item(item, "tags")
            status = current_status if status is None else status
            tag = (current_tags[0] if current_tags else "") if tag is None else tag
        values = (label, format_pages(self.pages.get(label, set())), status or "")
        tags = (tag,) if tag else ()
        if item is None:
            self.rows[label] = self.tree.insert("", "end", values=values, tags=tags)
        else:
            self.tree.item(item, values=values, tags=tags)

    def _open_exports(self) -> None:
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = str(EXPORT_DIR.resolve())
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    def _check_for_update(self) -> None:
        update = check_for_update(EXPORTER_VERSION)
        if update:
            self.events.put(("update", update.latest_version, update.release_url))

    def _on_close(self) -> None:
        if self._capture_running():
            answer = messagebox.askyesnocancel(TEXT["close_title"], TEXT["close_while_running"], parent=self.root)
            if answer is None:
                return
            if answer:
                self.close_when_done = True
                self._request_stop()
                return
        self.root.destroy()


class PromptDialog(tk.Toplevel):
    """Modal question: a text entry, or radio buttons when ``choices`` is given.

    ``result`` is the entered text / chosen value, or None when skipped.
    """

    def __init__(
        self,
        app: ExporterApp,
        title: str,
        message: str,
        choices: list[tuple[str, str]] | None = None,
    ) -> None:
        parent = app.root
        super().__init__(parent)
        self.withdraw()
        self.result: str | None = None
        self.title(title)
        self.configure(bg=app.colors["surface"])
        self.resizable(False, False)
        self.transient(parent)
        set_title_bar_theme(self, app.dark)

        pad = app.px(theme.LAYOUT["padding"])
        frame = ttk.Frame(self, style="Card.TFrame", padding=pad + app.px(4))
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=message, style="Card.TLabel", wraplength=app.px(380), justify="left").pack(
            anchor="w", pady=(0, app.px(10))
        )

        self.value = tk.StringVar()
        if choices:
            for value, label in choices:
                ttk.Radiobutton(frame, text=label, value=value, variable=self.value).pack(anchor="w", pady=app.px(1))
        else:
            entry = ttk.Entry(frame, textvariable=self.value)
            entry.pack(fill="x")
            entry.focus_set()

        buttons = ttk.Frame(frame, style="Card.TFrame")
        buttons.pack(fill="x", pady=(pad, 0))
        ttk.Button(buttons, text=TEXT["ok"], style="Accent.TButton", command=self._ok).pack(side="right")
        ttk.Button(buttons, text=TEXT["skip"], command=self.destroy).pack(side="right", padx=(0, app.px(8)))

        self.bind("<Return>", lambda _event: self._ok())
        self.bind("<Escape>", lambda _event: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_reqwidth()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.deiconify()
        self.grab_set()
        self.wait_window()

    def _ok(self) -> None:
        self.result = self.value.get().strip() or None
        self.destroy()


class Tooltip:
    """Small hover label for icon-only widgets; ``text`` is called each time so it can change."""

    DELAY_MS = 500

    def __init__(self, app: ExporterApp, widget: tk.Widget, text: Callable[[], str]) -> None:
        self.app = app
        self.widget = widget
        self.text = text
        self.window: tk.Toplevel | None = None
        self.pending: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._hide()
        self.pending = self.widget.after(self.DELAY_MS, self._show)

    def _show(self) -> None:
        self.pending = None
        c, px = self.app.colors, self.app.px
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.attributes("-topmost", True)
        tk.Label(
            self.window,
            text=self.text(),
            font=theme.FONTS["hint"],
            background=c["surface_alt"],
            foreground=c["text"],
            padx=px(8),
            pady=px(4),
            borderwidth=1,
            relief="solid",
        ).pack()
        self.window.update_idletasks()
        # Right-align under the widget so a tooltip near the window edge stays on screen.
        x = self.widget.winfo_rootx() + self.widget.winfo_width() - self.window.winfo_reqwidth()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + px(4)
        self.window.geometry(f"+{x}+{y}")

    def _hide(self, _event=None) -> None:
        if self.pending is not None:
            self.widget.after_cancel(self.pending)
            self.pending = None
        if self.window is not None:
            self.window.destroy()
            self.window = None


def load_palette() -> str:
    """The palette saved by the theme toggle, or theme.PALETTE on first launch."""
    try:
        name = json.loads(PREFS_PATH.read_text(encoding="utf-8")).get("palette")
    except (OSError, ValueError, AttributeError):
        name = None
    return name if name in theme.PALETTES else theme.PALETTE


def save_palette(name: str) -> None:
    try:
        PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PREFS_PATH.write_text(json.dumps({"palette": name}), encoding="utf-8")
    except OSError:
        pass


def set_title_bar_theme(window: tk.Misc, dark: bool) -> None:
    """Ask Windows 10/11 to draw a dark or light title bar; a no-op elsewhere."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        window.update_idletasks()  # creates the native frame without mapping a withdrawn window
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(int(dark))
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        pass


def _enable_dpi_awareness() -> None:
    """Render crisply on high-DPI Windows displays instead of being bitmap-scaled."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    _enable_dpi_awareness()
    if "--smoke-test" in args:
        return _smoke_test()
    _use_writable_working_dir()
    root = tk.Tk()
    root.withdraw()
    ExporterApp(root)
    root.deiconify()
    root.mainloop()
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
    """Build the whole window once and exit; used by CI to check packaged builds.

    A windowed build has no console and shows a blocking dialog on an uncaught
    error, so failures are turned into exit code 1 instead.
    """
    try:
        root = tk.Tk()
        root.withdraw()
        ExporterApp(root)
        root.update()
        root.destroy()
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
