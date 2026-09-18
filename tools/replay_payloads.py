"""Replay a captured UDP payload JSON file through the decoder offline.

This lets you iterate on decoder changes without running the game. Capture a
file once with tools/capture_payloads.py, then replay it here as many times as
you want.

Usage:
    python tools/replay_payloads.py [capture.json] [--debug]

The capture file defaults to exports/capture.json. With --debug it also writes
the research CSV and diagnostics, matching the live-capture debug output.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nte_history_exporter.decoder.boundary import annotate_groups
from nte_history_exporter.export.csv_export import write_csv
from nte_history_exporter.export.json_export import build_export_json
from nte_history_exporter.live_capture.runner import export_paths
from nte_history_exporter.live_capture.session import LiveHistorySession, UdpPacket


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_source", nargs="?", default="exports/capture.json")
    parser.add_argument("--debug", action="store_true", help="also write the research CSV")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data = json.loads(Path(args.capture_source).read_text(encoding="utf-8"))
    local_ip = data.get("local_ip", "192.0.2.1")

    session = LiveHistorySession(local_ip)
    for packet in data["packets"]:
        session.process_packet(
            UdpPacket(
                timestamp=packet.get("timestamp", 0.0),
                src_ip=packet["src_ip"],
                dst_ip=packet["dst_ip"],
                src_port=packet["src_port"],
                dst_port=packet["dst_port"],
                payload=bytes.fromhex(packet["payload_hex"]),
                protocol=packet.get("protocol", "udp"),
            )
        )

    kinds = session.kinds_seen()
    if not kinds:
        print("No history pages were captured in this file.")
        return 1

    for kind in kinds:
        rows = session.build_rows(kind)
        if kind not in {"arc_miracle_box", "mystery_box"}:
            rows = annotate_groups(rows)
        csv_path, json_path = export_paths(kind, session.user_uid)
        if args.debug:
            write_csv(csv_path, rows)
        export = build_export_json(
            rows,
            [],
            source="replay",
            capture_source=Path(args.capture_source).name,
            user_uid=session.user_uid,
            server_id=session.server_id,
            pages_seen=[p[0] for p in session.best_run(kind)],
        )
        json_path.write_text(
            json.dumps(export, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        scan = export["scan"]
        print(
            f"{export['banner']['name']}: {scan['decoded_records']} decoded, "
            f"{scan['exported_records']} exported"
        )
        if args.debug:
            print(f"  CSV: {csv_path}")
        print(f"  JSON: {json_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
