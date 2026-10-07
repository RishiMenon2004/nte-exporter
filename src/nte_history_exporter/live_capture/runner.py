from __future__ import annotations

import json
import subprocess
import sys
import time
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from typing import Callable

from nte_history_exporter import console
from nte_history_exporter.constants import (
    history_base_kind,
    history_kind_meta,
    history_kind_pool_id,
)
from nte_history_exporter.decoder.achievement import (
    extract_achievement_records,
    reassemble_tcp_segments,
)
from nte_history_exporter.decoder.boundary import annotate_groups, select_continuous_run_from_page_1
from nte_history_exporter.export.csv_export import write_csv
from nte_history_exporter.export.json_export import (
    build_achievement_export_json,
    build_export_json,
)
from nte_history_exporter.live_capture.backends import open_capture_backend
from nte_history_exporter.live_capture.diagnostics import new_diagnostics_path, write_capture_diagnostics
from nte_history_exporter.live_capture.payload_export import write_payload_capture
from nte_history_exporter.live_capture.session import LiveHistorySession, UdpPacket
from nte_history_exporter.live_capture.stop_key import StopKeyMonitor
from nte_history_exporter.live_capture.windows_raw import detect_local_ipv4


EXPORT_PREFIXES = {
    "permanent": "Permanent",
    "limited_character": "Limited",
    "arc_miracle_box": "Arc",
    "mystery_box": "MysteryBox",
}

CAPTURE_SOURCE_LABELS = {
    "windows_raw": "windows_packet",
}


def copy_to_clipboard(text: str) -> bool:
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True
    except Exception:
        pass

    commands = []
    if sys.platform == "win32":
        commands.append(["clip"])
    elif sys.platform == "darwin":
        commands.append(["pbcopy"])
    else:
        commands.extend([["wl-copy"], ["xclip", "-selection", "clipboard"]])

    for command in commands:
        try:
            subprocess.run(command, input=text, text=True, check=True)
            return True
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    return False


def run_live_capture(
    *,
    interface_ip: str | None = None,
    capture_backend: str = "auto",
    copy_clipboard: bool = False,
    write_debug_csv: bool = False,
    user_uid: str | None = None,
    reporter=console,
    stop_requested: Callable[[], bool] | None = None,
) -> dict:
    """Capture live traffic until stopped, then write the exports.

    ``reporter`` receives every progress message and prompt; it defaults to the
    terminal ``console`` module and must provide the same functions. When
    ``stop_requested`` is given it replaces the press-any-key stop monitor.
    """
    local_ip = interface_ip or detect_local_ipv4()
    session = LiveHistorySession(local_ip)

    capture = open_capture_backend(local_ip, capture_backend)
    reporter.print_live_instructions(local_ip, capture.name, capture.detail)
    if capture.fallback_reason:
        reporter.print_capture_fallback(capture.fallback_reason)
    reported_missing_pages: dict[str, tuple[int, ...]] = {}
    active_gap_notices: set[str] = set()
    tcp_segments: dict[tuple[str, int, str, int], list[tuple[int, bytes]]] = {}
    achievement_records = []
    captured_packets: list[UdpPacket] = []

    try:
        with StopKeyMonitor() if stop_requested is None else nullcontext() as stop_key:
            should_stop = stop_requested or stop_key.pressed
            for packet in capture.packets():
                if should_stop():
                    break
                if packet is None:
                    continue
                if (
                    not achievement_records
                    and packet.protocol == "tcp"
                    and packet.payload
                    and packet.dst_ip == local_ip
                ):
                    flow = (packet.src_ip, packet.src_port, packet.dst_ip, packet.dst_port)
                    tcp_segments.setdefault(flow, []).append(
                        (packet.sequence_number, packet.payload)
                    )
                    if not achievement_records:
                        achievement_records = extract_achievement_records(
                            reassemble_tcp_segments(tcp_segments[flow])
                        )
                        if achievement_records:
                            in_game = [
                                record
                                for record in achievement_records
                                if not record.achievement_id.casefold().startswith(
                                    "playstation_"
                                )
                            ]
                            playstation = [
                                record
                                for record in achievement_records
                                if record.achievement_id.casefold().startswith(
                                    "playstation_"
                                )
                            ]
                            reporter.print_achievements_captured(
                                sum(record.completed for record in in_game),
                                sum(record.status == "in_progress" for record in in_game),
                                sum(record.completed for record in playstation),
                                sum(
                                    record.status == "in_progress"
                                    for record in playstation
                                ),
                            )
                udp_packet = UdpPacket(
                    timestamp=time.time(),
                    src_ip=packet.src_ip,
                    dst_ip=packet.dst_ip,
                    src_port=packet.src_port,
                    dst_port=packet.dst_port,
                    payload=packet.payload,
                    protocol=packet.protocol,
                )
                if write_debug_csv and packet.protocol == "udp":
                    captured_packets.append(udp_packet)
                pair_count_before = len(session.pairs)
                matched = session.process_packet(udp_packet)
                if matched:
                    affected_kinds = []
                    for pair in session.pairs[pair_count_before:]:
                        page = pair[0]
                        kind = pair[7] if len(pair) > 7 else "permanent"
                        label = history_kind_meta(kind)["name"]
                        was_replacement = any(
                            existing[0] == page
                            and (existing[7] if len(existing) > 7 else "permanent") == kind
                            for existing in session.pairs[:pair_count_before]
                        )
                        reporter.print_page_captured(label, page, recaptured=was_replacement)
                        if kind not in affected_kinds:
                            affected_kinds.append(kind)

                    for kind in affected_kinds:
                        label = history_kind_meta(kind)["name"]
                        missing_pages = tuple(session.missing_pages(kind))
                        previously_missing = reported_missing_pages.get(kind, ())
                        if missing_pages and kind not in active_gap_notices:
                            reporter.print_missing_pages(label, list(missing_pages))
                            active_gap_notices.add(kind)
                        elif previously_missing and not missing_pages:
                            reporter.print_page_gap_recovered(label)
                            active_gap_notices.discard(kind)
                        reported_missing_pages[kind] = missing_pages
    finally:
        stats = capture.stats()
        capture.close()

    exports = []
    achievement_path = None
    diagnostics_path = None
    payloads_path = None
    if write_debug_csv:
        diagnostics_path = new_diagnostics_path()
        write_capture_diagnostics(diagnostics_path, session.diagnostic_report())
        payloads_path = diagnostics_path.with_name(
            diagnostics_path.name.replace(".diagnostics.json", ".payloads.json")
        )
        uids = [u for u in (user_uid, session.user_uid) if u]
        write_payload_capture(payloads_path, captured_packets, local_ip, known_uids=uids)
    resolved_user_uid = user_uid or session.user_uid
    if (session.kinds_seen() or achievement_records) and not resolved_user_uid:
        resolved_user_uid = reporter.prompt_user_uid()
    if achievement_records:
        achievement_path = _achievement_path(resolved_user_uid)
        achievement_export = build_achievement_export_json(
            achievement_records,
            source="live_capture",
            capture_source=CAPTURE_SOURCE_LABELS.get(capture.name, capture.name),
            user_uid=resolved_user_uid,
            server_id=session.server_id,
        )
        achievement_path.write_text(
            json.dumps(achievement_export, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    resolved_server_id = session.server_id
    if session.kinds_seen() and not resolved_server_id:
        resolved_server_id = reporter.prompt_server_id()
    capture_source = CAPTURE_SOURCE_LABELS.get(capture.name, capture.name)
    for kind in session.export_kinds():
        rows, warnings, pages_seen, pools = collect_export_rows(session, kind)
        csv_path, json_path = export_paths(kind, resolved_user_uid)
        if write_debug_csv:
            write_csv(csv_path, rows)
        export = build_export_json(
            rows,
            warnings,
            source="live_capture",
            capture_source=capture_source,
            user_uid=resolved_user_uid,
            server_id=resolved_server_id,
            pages_seen=pages_seen,
            pools=pools,
        )
        payload = json.dumps(export, ensure_ascii=False, indent=2)
        json_path.write_text(payload, encoding="utf-8")
        exports.append(
            {
                "kind": kind,
                "csv_path": csv_path if write_debug_csv else None,
                "diagnostics_path": diagnostics_path if write_debug_csv else None,
                "payloads_path": payloads_path if write_debug_csv else None,
                "json_path": json_path,
                "export": export,
                "payload": payload,
            }
        )

    reporter.print_results_header()
    if stats:
        reporter.print_capture_stats(
            stats.received,
            stats.dropped,
            stats.interface_dropped,
        )
    if stats:
        reporter.print_blank()

    if not exports:
        if achievement_path is not None:
            reporter.print_success("Achievement export complete.")
            reporter.print_note("No pull history was captured (this is fine if you only wanted achievements).")
            reporter.print_blank()
            reporter.print_note(f"Export written: {achievement_path}")
        else:
            reporter.print_problem("No history pages were captured.")
            reporter.print_note("Reopen a supported history screen and scroll from page 1.")
            reporter.print_note("If no page messages appear, return to the main menu and re-enter the game.")
        if diagnostics_path is not None:
            reporter.print_note(f"Diagnostics written: {diagnostics_path}")
        if payloads_path is not None:
            reporter.print_note(f"Replay payloads written: {payloads_path}")
        return {
            "exports": [],
            "diagnostics_path": diagnostics_path,
            "payloads_path": payloads_path,
            "achievement_path": achievement_path,
        }

    for item in exports:
        scan = item["export"]["scan"]
        reporter.print_export_summary(
            item["export"]["banner"]["name"],
            scan["decoded_records"],
            scan["exported_records"],
            scan["skipped_records"],
        )
        for warning in scan["warnings"]:
            reporter.print_warning(warning["code"], warning["reason"], warning.get("records"))

    reporter.print_blank()
    for item in exports:
        if item["csv_path"] is not None:
            reporter.print_note(f"CSV written: {item['csv_path']}")
        reporter.print_note(f"Export written: {item['json_path']}")
    if achievement_path is not None:
        reporter.print_blank()
        reporter.print_note(f"Export written: {achievement_path}")
    if diagnostics_path is not None:
        reporter.print_note(f"Diagnostics written: {diagnostics_path}")
    if payloads_path is not None:
        reporter.print_note(f"Replay payloads written: {payloads_path}")

    if copy_clipboard and len(exports) == 1:
        if copy_to_clipboard(exports[0]["payload"]):
            reporter.print_success("Export copied to clipboard - paste it straight into your tracker.")
        else:
            reporter.print_note("Clipboard tool unavailable; use the JSON file shown above.")
    elif copy_clipboard and len(exports) > 1:
        reporter.print_note("Multiple banners captured; clipboard copy skipped so one export")
        reporter.print_note("does not overwrite another.")
    return {
        "exports": exports,
        "diagnostics_path": diagnostics_path,
        "payloads_path": payloads_path,
        "achievement_path": achievement_path,
    }


def _achievement_path(user_uid: str | None = None) -> Path:
    export_dir = Path("exports")
    export_dir.mkdir(parents=True, exist_ok=True)
    uid_prefix = _safe_filename_part(user_uid) if user_uid else "unknown"
    base = export_dir / f"{uid_prefix}_Achievements_{datetime.now():%Y%m%d_%H%M%S}"
    path = base.with_suffix(".json")
    counter = 2
    while path.exists():
        path = export_dir / f"{base.name}_{counter}.json"
        counter += 1
    return path


def collect_export_rows(
    session: LiveHistorySession, export_kind: str
) -> tuple[list[dict], list[dict], list[int] | None, list[dict] | None]:
    rows: list[dict] = []
    warnings: list[dict] = []
    pages_seen: list[int] | None = None
    pools: list[dict] = []
    for kind in session.kinds_seen():
        if history_base_kind(kind) != export_kind:
            continue
        best_run, run_warnings = select_continuous_run_from_page_1(session.pairs_for_kind(kind))
        kind_rows = session.build_rows(kind)
        if export_kind not in {"arc_miracle_box", "mystery_box"}:
            kind_rows = annotate_groups(kind_rows)
        rows += kind_rows
        warnings += run_warnings
        pages = [p[0] for p in best_run]
        if pool_id := history_kind_pool_id(kind):
            pools.append(
                {"pool_id": pool_id, "pages_seen": pages, "exported_records": len(kind_rows)}
            )
        else:
            pages_seen = pages
    return rows, warnings, pages_seen, pools or None


def export_paths(kind: str, user_uid: str | None = None) -> tuple[Path, Path]:
    export_dir = Path("exports")
    export_dir.mkdir(parents=True, exist_ok=True)
    prefix = EXPORT_PREFIXES.get(kind, "History")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    uid_prefix = _safe_filename_part(user_uid) if user_uid else "unknown"
    base_name = f"{uid_prefix}_{prefix}_{stamp}"
    base = export_dir / base_name
    csv_path = base.with_suffix(".csv")
    json_path = base.with_suffix(".json")
    counter = 2
    while csv_path.exists() or json_path.exists():
        base = export_dir / f"{base_name}_{counter}"
        csv_path = base.with_suffix(".csv")
        json_path = base.with_suffix(".json")
        counter += 1
    return csv_path, json_path


def _safe_filename_part(value: str | None) -> str:
    if not value:
        return "unknown"
    cleaned = "".join(ch for ch in value.strip() if ch.isalnum() or ch in ("-", "_"))
    return cleaned or "unknown"
