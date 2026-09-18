from tests.support import *  # noqa: F401,F403

import json
import struct
from tempfile import TemporaryDirectory
from pathlib import Path

from nte_history_exporter.live_capture.payload_export import (
    CAPTURE_FORMAT,
    CAPTURE_FORMAT_VERSION,
    ANONYMOUS_LOCAL_IP,
    ANONYMOUS_UID,
    new_payloads_path,
    sanitize_payload_packets,
    write_payload_capture,
)
from nte_history_exporter.live_capture.session import LiveHistorySession, UdpPacket


class PayloadExportTests(unittest.TestCase):
    def test_sanitize_payload_packets_scrubs_ips_and_uids(self):
        real_local_ip = "192.168.1.50"
        real_remote_ip = "47.100.20.30"
        real_uid = 123456789012
        real_uid_bytes = struct.pack("<Q", real_uid)
        real_uid_str = str(real_uid).encode("ascii")

        # Fake payload containing UID both binary and text
        payload = b"HEADER" + real_uid_bytes + b"MIDDLE" + real_uid_str + b"TRAILER"

        packets = [
            UdpPacket(
                timestamp=100.0,
                src_ip=real_local_ip,
                dst_ip=real_remote_ip,
                src_port=54321,
                dst_port=8888,
                payload=payload,
                protocol="udp",
            ),
            UdpPacket(
                timestamp=101.5,
                src_ip=real_remote_ip,
                dst_ip=real_local_ip,
                src_port=8888,
                dst_port=54321,
                payload=b"RESPONSE" + real_uid_bytes,
                protocol="udp",
            ),
            UdpPacket(
                timestamp=102.0,
                src_ip=real_local_ip,
                dst_ip=real_remote_ip,
                src_port=54321,
                dst_port=8888,
                payload=b"TCP_SHOULD_BE_IGNORED",
                protocol="tcp",
            ),
        ]

        sanitized = sanitize_payload_packets(packets, local_ip=real_local_ip, known_uids=[str(real_uid)])

        # Only UDP packets included
        self.assertEqual(len(sanitized), 2)

        # Timestamps relative
        self.assertEqual(sanitized[0]["timestamp"], 0.0)
        self.assertEqual(sanitized[1]["timestamp"], 1.5)

        # IPs sanitized to documentation ranges
        self.assertEqual(sanitized[0]["src_ip"], ANONYMOUS_LOCAL_IP)
        self.assertEqual(sanitized[0]["dst_ip"], "198.51.100.1")
        self.assertEqual(sanitized[1]["src_ip"], "198.51.100.1")
        self.assertEqual(sanitized[1]["dst_ip"], ANONYMOUS_LOCAL_IP)

        # UID scrubbed
        p1_payload = bytes.fromhex(sanitized[0]["payload_hex"])
        self.assertNotIn(real_uid_bytes, p1_payload)
        self.assertNotIn(real_uid_str, p1_payload)
        self.assertIn(struct.pack("<Q", ANONYMOUS_UID), p1_payload)
        self.assertIn(str(ANONYMOUS_UID).encode("ascii"), p1_payload)

        p2_payload = bytes.fromhex(sanitized[1]["payload_hex"])
        self.assertNotIn(real_uid_bytes, p2_payload)
        self.assertIn(struct.pack("<Q", ANONYMOUS_UID), p2_payload)

    def test_write_payload_capture_and_replay(self):
        with TemporaryDirectory() as tmpdir:
            out_file = Path(tmpdir) / "test.payloads.json"
            real_local = "10.0.0.5"
            real_remote = "198.51.100.99"

            # Create minimal valid request and response
            request = bytearray(45)
            request[31:35] = (4).to_bytes(4, "little")
            request[35:39] = (4220).to_bytes(4, "little")
            request[40:44] = (4).to_bytes(4, "little")

            response = bytearray(220)
            response[0x50:0x50 + len(MARKER)] = MARKER
            response[0x50 + len(MARKER):0x50 + len(MARKER) + 8] = (
                2556647947780680000
            ).to_bytes(8, "little")

            packets = [
                UdpPacket(1.0, real_local, real_remote, 50000, 40000, bytes(request)),
                UdpPacket(1.2, real_remote, real_local, 40000, 50000, bytes(response)),
            ]

            write_payload_capture(out_file, packets, local_ip=real_local)

            # Check JSON file content
            data = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(data["format"], CAPTURE_FORMAT)
            self.assertEqual(data["format_version"], CAPTURE_FORMAT_VERSION)
            self.assertTrue(data["anonymized"])
            self.assertEqual(data["local_ip"], ANONYMOUS_LOCAL_IP)
            self.assertEqual(len(data["packets"]), 2)

            # Replay through LiveHistorySession
            replay_session = LiveHistorySession(data["local_ip"])
            for p in data["packets"]:
                replay_session.process_packet(
                    UdpPacket(
                        timestamp=p["timestamp"],
                        src_ip=p["src_ip"],
                        dst_ip=p["dst_ip"],
                        src_port=p["src_port"],
                        dst_port=p["dst_port"],
                        payload=bytes.fromhex(p["payload_hex"]),
                    )
                )

            self.assertEqual(len(replay_session.pairs), 1)
            self.assertEqual(replay_session.last_page_seen, 1)
