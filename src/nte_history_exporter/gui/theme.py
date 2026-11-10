"""Window settings and wording of the desktop GUI.

Colors, fonts and layout live in web/style.css, and tracker sites in trackers.py.
See docs/gui.md for a walkthrough.
"""

from __future__ import annotations

# Pixels at 100% display scaling; the webview applies the OS scale factor.
WINDOW = {
    "size": (1040, 740),  # initial width, height
    "min_size": (900, 660),
    "background": "#1d1d1d",  # shown for a moment before the page paints
}

TEXT = {
    "window_title": "NTE History Exporter",
    "title": "NTE History Exporter",
    # Status-bar credit, drawn as: credit_before ♥ credit_after
    "credit_before": "Created with ",
    "credit_after": " by Golumpa, maintained by RishiMenon2004",
    "update_available": "Update available: {version}  ↗",
    "update_install": "Update to {version}",
    "update_downloading": "Downloading update… {percent}%",
    "update_installing": "Installing update…",
    "update_failed": "Could not update ({reason}). Opening the release page instead.",
    "update_blocked": "Finish the capture before updating.",
    # Sidebar
    "settings": "Settings",
    "backend": "Capture backend",
    "backend_hint": "auto prefers Npcap and falls back to raw sockets",
    "interface_ip": "Interface IP",
    "interface_ip_example": "e.g. 192.168.1.20",
    "interface_ip_hint": "Only needed if nothing is captured, such as on a VPN",
    "user_uid": "User UID override",
    "user_uid_example": "e.g. 123456789",
    "user_uid_hint": "Leave blank to detect from the capture",
    "copy_clipboard": "Copy export to clipboard",
    "advanced": "Advanced",
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
    "open_in": "Import in",
    "captured_empty": "Nothing captured yet.",
    "activity": "Activity",
    "ready": "Ready. Use the game, then click Stop & export when finished.",
    "gap_hint": "Close and reopen this history board, then scroll down until the gap is recovered.",
    "copied": "Export copied to clipboard - paste it straight into your tracker.",
    "copy_failed": "Could not reach the clipboard. The export is still in the exports folder.",
    "copy_skipped": "Multiple banners captured; clipboard copy skipped so one export does not overwrite another.",
    "achievements_row": "Achievements",
    # Status bar
    "status_idle": "Ready to capture",
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
    "dismiss": "Close",
    "skip": "Skip",
    "close_title": "Capture running",
    "close_while_running": "A capture is still running. Stop it and save the exports before closing?",
    "close_save": "Save & close",
    "close_discard": "Close without saving",
    "close_cancel": "Keep capturing",
    "capture_failed_title": "Capture failed",
    "webview_missing": (
        "The window could not be opened.\n\n{error}\n\n"
        "On Windows this usually means the Microsoft Edge WebView2 Runtime is missing. "
        "Install it from https://developer.microsoft.com/microsoft-edge/webview2/ and try again."
    ),
    "capture_permission_hint": (
        "Install or enable Npcap (or libpcap). If you use the raw backend on Windows, "
        "run the exporter as Administrator; on Linux/macOS, try sudo."
    ),
}
