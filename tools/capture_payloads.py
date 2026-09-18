"""Capture raw UDP payloads to a replayable JSON file.

This lets you record the game's history traffic once and replay it offline
through the decoder as many times as you want, without running the game.

Usage:
    python tools/capture_payloads.py [--out capture.json] [--interface-ip IP]
                                     [--capture-backend auto|libpcap|raw]

Press Ctrl+C (or the Stop key) to stop capturing and save the file.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nte_history_exporter import console
from nte_history_exporter.constants import POOL_META
from nte_history_exporter.live_capture.backends import open_capture_backend
from nte_history_exporter.live_capture.payload_export import write_payload_capture
from nte_history_exporter.live_capture.runner import detect_local_ipv4
from nte_history_exporter.live_capture.session import LiveHistorySession, UdpPacket
from nte_history_exporter.live_capture.stop_key import StopKeyMonitor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="exports/capture.json", help="output JSON file path")
    parser.add_argument("--interface-ip", default=None, help="local IPv4 address to bind")
    parser.add_argument(
        "--capture-backend",
        choices=["auto", "libpcap", "raw"],
        default="auto",
        help="capture backend (default: auto)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    local_ip = args.interface_ip or detect_local_ipv4()
    capture = open_capture_backend(local_ip, args.capture_backend)
    print(f"Capturing on {local_ip} ({capture.name}). Open the game history board and scroll.")
    print("Press Ctrl+C to stop and save.")

    session = LiveHistorySession(local_ip)
    udp_packets: list[UdpPacket] = []
    start = time.time()
    reported_missing_pages: dict[str, tuple[int, ...]] = {}
    active_gap_notices: set[str] = set()
    try:
        with StopKeyMonitor() as stop_key:
            for packet in capture.packets():
                if stop_key.pressed():
                    break
                if packet is None or packet.protocol != "udp":
                    continue
                timestamp = round(time.time() - start, 6)
                udp_packet = UdpPacket(
                    timestamp=timestamp,
                    src_ip=packet.src_ip,
                    dst_ip=packet.dst_ip,
                    src_port=packet.src_port,
                    dst_port=packet.dst_port,
                    payload=packet.payload,
                    protocol=packet.protocol,
                )
                udp_packets.append(udp_packet)
                pair_count_before = len(session.pairs)
                matched = session.process_packet(udp_packet)
                if not matched:
                    continue
                affected_kinds = []
                for pair in session.pairs[pair_count_before:]:
                    page = pair[0]
                    kind = pair[7] if len(pair) > 7 else "permanent"
                    label = POOL_META.get(kind, POOL_META["permanent"])["name"]
                    was_replacement = any(
                        existing[0] == page
                        and (existing[7] if len(existing) > 7 else "permanent") == kind
                        for existing in session.pairs[:pair_count_before]
                    )
                    console.print_page_captured(label, page, recaptured=was_replacement)
                    if kind not in affected_kinds:
                        affected_kinds.append(kind)

                for kind in affected_kinds:
                    label = POOL_META.get(kind, POOL_META["permanent"])["name"]
                    missing_pages = tuple(session.missing_pages(kind))
                    previously_missing = reported_missing_pages.get(kind, ())
                    if missing_pages and kind not in active_gap_notices:
                        console.print_missing_pages(label, list(missing_pages))
                        active_gap_notices.add(kind)
                    elif previously_missing and not missing_pages:
                        console.print_page_gap_recovered(label)
                        active_gap_notices.discard(kind)
                    reported_missing_pages[kind] = missing_pages
    except KeyboardInterrupt:
        pass
    finally:
        capture.close()

    out = Path(args.out)
    uids = [session.user_uid] if session.user_uid else []
    write_payload_capture(out, udp_packets, local_ip, known_uids=uids)
    print(f"Saved {len(udp_packets)} sanitized UDP packets to {out}")

    console.print_results_header()
    kinds = session.kinds_seen()
    if not kinds:
        console.print_problem("No history pages were captured.")
        console.print_note("Reopen a supported history screen and scroll from page 1.")
        return 0
    for kind in kinds:
        label = POOL_META.get(kind, POOL_META["permanent"])["name"]
        pages = [pair[0] for pair in session.best_run(kind)]
        missing = session.missing_pages(kind)
        page_text = ", ".join(str(page) for page in pages) if pages else "none"
        suffix = f"  (missing: {', '.join(str(p) for p in missing)})" if missing else ""
        print(f"  {label:<30}pages {page_text}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
