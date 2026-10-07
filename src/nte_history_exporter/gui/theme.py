"""Look and feel of the desktop GUI.

Everything a person is likely to want to tweak lives here: colors, fonts,
sizes and the text shown in the window. See docs/gui.md for a walkthrough.
"""

from __future__ import annotations

import sys

# Palette used on first launch. After the header toggle is clicked, the
# choice is saved and used on later launches instead.
PALETTE = "dark"

# The two palettes the header toggle switches between. DARK_PALETTE also gets a
# dark Windows title bar.
DARK_PALETTE = "dark"
LIGHT_PALETTE = "light"

# Color tokens. Every widget style in app.py is built from these keys, so a new
# palette only needs to define the same keys.
PALETTES = {
    "dark": {
        "bg": "#15171c",  # window background
        "surface": "#1e2128",  # cards (sidebar, captured list, activity log)
        "surface_alt": "#2a2e37",  # secondary buttons, table headings
        "field": "#121419",  # inputs, table body, log body
        "border": "#353a45",
        "text": "#e7e9ee",
        "muted": "#99a0ad",  # hints, secondary text
        "accent": "#4cc2ff",  # primary button, focus ring, links
        "accent_hover": "#7ad3ff",
        "accent_text": "#08131c",  # text drawn on accent/danger buttons
        "success": "#5fd38d",
        "warning": "#f2c94c",
        "error": "#ff6b6b",
        "error_hover": "#ff8f8f",
        "select": "#2c3a50",  # selected table row / selected text
    },
    "light": {
        "bg": "#f3f4f7",
        "surface": "#ffffff",
        "surface_alt": "#e6e8ee",
        "field": "#fafbfc",
        "border": "#d3d7df",
        "text": "#1b1e24",
        "muted": "#5f6673",
        "accent": "#0a6fd1",
        "accent_hover": "#2b86e0",
        "accent_text": "#ffffff",
        "success": "#1e8a4c",
        "warning": "#a86a00",
        "error": "#c93434",
        "error_hover": "#dd4c4c",
        "select": "#d6e6fa",
    },
}

# FONT_SCALE multiplies every font size below. Tk on macOS draws 1 pt as 1 px,
# so sizes chosen on Windows look about 3/4 as big there without it.
FONT_SCALE = 1.0
if sys.platform == "win32":
    FONT_FAMILY, MONO_FAMILY = "Segoe UI", "Consolas"
elif sys.platform == "darwin":
    FONT_FAMILY, MONO_FAMILY = "Helvetica Neue", "Menlo"
    FONT_SCALE = 4 / 3
else:
    FONT_FAMILY, MONO_FAMILY = "DejaVu Sans", "DejaVu Sans Mono"


def _pt(size: float) -> int:
    return round(size * FONT_SCALE)


# (family, size in points, optional style)
FONTS = {
    "title": (FONT_FAMILY, _pt(17), "bold"),
    "subtitle": (FONT_FAMILY, _pt(9)),
    "heading": (FONT_FAMILY, _pt(10), "bold"),
    "body": (FONT_FAMILY, _pt(10)),
    "hint": (FONT_FAMILY, _pt(8)),
    "log": (MONO_FAMILY, _pt(9)),
}

# Header theme-toggle icons: a sun while dark, a moon while light. Each entry is
# tried in order and the first installed font wins; family None means the body
# font (macOS/Linux render these symbols well; Windows' Segoe UI does not).
THEME_ICONS = {
    "to_light": [("Segoe Fluent Icons", "\ue706"), ("Segoe MDL2 Assets", "\ue706"), (None, "☀")],
    "to_dark": [("Segoe Fluent Icons", "\ue708"), ("Segoe MDL2 Assets", "\ue708"), (None, "☾")],
}
THEME_ICON_SIZE = _pt(13)  # points

# Sizes below are in pixels at 100% display scaling; the app multiplies them by
# the OS scale factor, so at 150% scaling they become 1.5x larger.
WINDOW = {
    "size": (980, 700),  # initial width, height
    "min_size": (860, 640),
}

LAYOUT = {
    "padding": 16,  # space around the window edge and inside cards
    "gap": 12,  # space between cards
    "sidebar_width": 260,  # wrap width for sidebar text; the sidebar grows to fit it
    "row_height": 26,  # captured-list row height
}

# Activity-log line styles: tag name -> palette key for the text color.
LOG_COLORS = {
    "info": "text",
    "muted": "muted",
    "success": "success",
    "warning": "warning",
    "error": "error",
    "accent": "accent",
}

TEXT = {
    "window_title": "NTE History Exporter",
    "title": "NTE History Exporter",
    "subtitle": "{game} history and achievements → JSON",
    # Credit after the subtitle, drawn as: credit_before ♥ credit_after
    "credit_before": "  ·  Created with ",
    "credit_after": " by Golumpa, maintained by RishiMenon2004",
    "update_available": "Update available: {version}  ↗",
    "theme_to_light": "Switch to light mode",  # toggle tooltip while dark
    "theme_to_dark": "Switch to dark mode",  # toggle tooltip while light
    # Sidebar
    "settings": "Capture settings",
    "backend": "Capture backend",
    "backend_hint": "auto prefers Npcap and falls back to raw sockets",
    "interface_ip": "Interface IP",
    "interface_ip_hint": "Leave blank to detect automatically",
    "user_uid": "User UID override",
    "user_uid_hint": "Leave blank to detect from the capture",
    "copy_clipboard": "Copy export to clipboard",
    "debug": "Write debug files",
    "start": "Start capture",
    "stop": "Stop & export",
    "stopping": "Saving exports…",
    "open_exports": "Open exports folder",
    "how_to": "How to capture",
    # Shown in the activity log while idle, one numbered step each.
    "instructions": (
        "Click Start capture before pressing Start on the game's main menu. This lets the "
        "exporter capture achievements and detect your UID and server automatically.",
        "Open a supported history screen (Standard or Limited Character Board, Arc Miracle "
        "Box or Mystery Box), start at page 1 and scroll through every page, then one more "
        "so the final pull group can be confirmed.",
        "Repeat for any other boards you want; one session can capture several.",
        "Click Stop & export. Files are written to the exports folder.",
    ),
    # Main area
    "captured": "Captured",
    "col_banner": "Banner",
    "col_pages": "Pages",
    "col_status": "Status",
    "activity": "Activity",
    "ready": "Ready. Use the game, then click Stop & export when finished.",
    "gap_hint": "Close and reopen this history board, then scroll down until the gap is recovered.",
    "copied": "Export copied to clipboard - paste it straight into your tracker.",
    "copy_skipped": "Multiple banners captured; clipboard copy skipped so one export does not overwrite another.",
    "achievements_row": "Achievements",
    # Status bar
    "status_idle": "Ready. Click Start capture, then use the game.",
    "status_listening": "Listening on {ip} via {backend}. Click Stop & export when finished.",
    "status_saving": "Stopping capture and saving exports…",
    "status_done": "Done. {count} file(s) saved to the exports folder.",
    "status_failed": "Capture failed. See the activity log for details.",
    # Dialogs
    "uid_prompt_title": "User UID",
    "uid_prompt": (
        "Your user UID was not detected in this capture.\n\n"
        "Enter your NTE user UID so the export can be named and linked correctly. "
        "Leaving it blank may prevent import on some trackers."
    ),
    "server_prompt_title": "Account server",
    "server_prompt": "The account server was not detected in this capture. Choose the server this account uses:",
    "ok": "OK",
    "skip": "Skip",
    "close_title": "Capture running",
    "close_while_running": "A capture is still running.\n\nStop it and save the exports before closing?",
    "capture_failed_title": "Capture failed",
    "capture_permission_hint": (
        "Install or enable Npcap (or libpcap). If you use the raw backend on Windows, "
        "run the exporter as Administrator; on Linux/macOS, try sudo."
    ),
}
