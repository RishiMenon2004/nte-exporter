from __future__ import annotations

import json
import struct
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from nte_history_exporter.decoder.user_uid import extract_user_uid_candidates
from nte_history_exporter.live_capture.session import UdpPacket

CAPTURE_FORMAT = "nte-udp-payload-capture"
CAPTURE_FORMAT_VERSION = 1
ANONYMOUS_LOCAL_IP = "192.0.2.1"
ANONYMOUS_REMOTE_PREFIX = "198.51.100."
ANONYMOUS_UID = 100_000_000_000


def new_payloads_path(output_dir: str | Path = "exports") -> Path:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = directory / f"Capture_{stamp}.payloads.json"
    counter = 2
    while path.exists():
        path = directory / f"Capture_{stamp}_{counter}.payloads.json"
        counter += 1
    return path


def sanitize_payload_packets(
    packets: list[UdpPacket],
    local_ip: str,
    known_uids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Sanitize network packets to preserve full replayability while scrubbing private data.

    - Local host IP is mapped to RFC 5737 documentation IP 192.0.2.1.
    - Remote game server IPs are mapped to 198.51.100.x sequentially.
    - Client and server ports are mapped consistently per stream (50000+ / 40000+).
    - User UIDs (both 64-bit LE integer and ASCII string) are scrubbed to 100000000000.
    - Timestamps are normalized relative to the start of the session.
    """
    remote_ip_map: dict[str, str] = {}

    def anonymize_ip(ip: str) -> str:
        if ip == local_ip:
            return ANONYMOUS_LOCAL_IP
        if ip not in remote_ip_map:
            remote_ip_map[ip] = f"{ANONYMOUS_REMOTE_PREFIX}{len(remote_ip_map) + 1}"
        return remote_ip_map[ip]

    client_port_map: dict[int, int] = {}
    server_port_map: dict[int, int] = {}

    def anonymize_port(port: int, is_client: bool) -> int:
        target_map = client_port_map if is_client else server_port_map
        base = 50000 if is_client else 40000
        if port not in target_map:
            target_map[port] = base + len(target_map)
        return target_map[port]

    # Collect any known or detected UIDs to scrub
    uids_to_scrub: set[int] = set()
    for uid in known_uids:
        if uid and str(uid).isdigit():
            uids_to_scrub.add(int(uid))

    for packet in packets:
        for candidate in extract_user_uid_candidates(packet.payload):
            if candidate.isdigit():
                uids_to_scrub.add(int(candidate))

    dummy_uid_u64 = struct.pack("<Q", ANONYMOUS_UID)
    dummy_uid_str = str(ANONYMOUS_UID).encode("ascii")

    scrub_targets: list[tuple[bytes, bytes]] = []
    for uid in uids_to_scrub:
        if uid == ANONYMOUS_UID:
            continue
        scrub_targets.append((struct.pack("<Q", uid), dummy_uid_u64))
        scrub_targets.append((str(uid).encode("ascii"), dummy_uid_str))

    first_time: float | None = None
    sanitized: list[dict[str, Any]] = []

    for packet in packets:
        if packet.protocol != "udp":
            continue
        if first_time is None:
            first_time = packet.timestamp

        rel_time = round(packet.timestamp - first_time, 6)
        src_is_client = (packet.src_ip == local_ip)
        dst_is_client = (packet.dst_ip == local_ip)

        anon_src_ip = anonymize_ip(packet.src_ip)
        anon_dst_ip = anonymize_ip(packet.dst_ip)
        anon_src_port = anonymize_port(packet.src_port, src_is_client)
        anon_dst_port = anonymize_port(packet.dst_port, dst_is_client)

        payload = packet.payload
        for target_bytes, replacement in scrub_targets:
            if target_bytes in payload:
                payload = payload.replace(target_bytes, replacement)

        sanitized.append(
            {
                "timestamp": rel_time,
                "src_ip": anon_src_ip,
                "dst_ip": anon_dst_ip,
                "src_port": anon_src_port,
                "dst_port": anon_dst_port,
                "payload_hex": payload.hex(),
                "protocol": packet.protocol,
            }
        )

    return sanitized


def write_payload_capture(
    path: str | Path,
    packets: list[UdpPacket],
    local_ip: str,
    known_uids: Iterable[str] = (),
) -> None:
    sanitized_packets = sanitize_payload_packets(packets, local_ip, known_uids)
    doc = {
        "format": CAPTURE_FORMAT,
        "format_version": CAPTURE_FORMAT_VERSION,
        "anonymized": True,
        "local_ip": ANONYMOUS_LOCAL_IP,
        "packet_count": len(sanitized_packets),
        "packets": sanitized_packets,
    }
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
