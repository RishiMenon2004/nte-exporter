from tests.support import *  # noqa: F401,F403

from datetime import datetime, timezone

from nte_history_exporter.constants import MYSTERY_BOX_MARKER
from nte_history_exporter.live_capture.runner import collect_export_rows
from nte_history_exporter.decoder.mystery_box import (
    build_mystery_box_rows_from_pairs,
    is_mystery_box_history_request,
    mystery_box_request_page,
    parse_mystery_box_response,
)


def mystery_box_request(page: int) -> bytes:
    request = bytearray(54)
    request[26:30] = (2060).to_bytes(4, "little")
    request[31:35] = (page * 2).to_bytes(4, "little")
    request[35:39] = (2110).to_bytes(4, "little")
    request[40:44] = (2).to_bytes(4, "little")
    request[44:48] = (2060).to_bytes(4, "little")
    request[49:53] = (10).to_bytes(4, "little")
    request[53] = 6
    return bytes(request)


def mystery_box_response(records: list[tuple[str, int, datetime]]) -> bytes:
    body = bytearray()
    for reward_id, quantity, timestamp in records:
        encoded_id = reward_id.encode("utf-8") + b"\0"
        ticks = int(timestamp.timestamp() * 10_000_000) + 621_355_968_000_000_000
        body += len(encoded_id).to_bytes(4, "little")
        body += encoded_id
        body += quantity.to_bytes(4, "little")
        body += b"\x01"
        body += ticks.to_bytes(8, "little")
    return (
        bytes(50)
        + MYSTERY_BOX_MARKER
        + b"\0"
        + bytes(4)
        + len(body).to_bytes(4, "little")
        + len(records).to_bytes(4, "little")
        + body
        + b"\x03"
    )


POOLED_REQUEST = bytes.fromhex(
    "04847a06edffffff7f2012014c664e0cbe1318ba4b50070000000c08000000020000001e20000000"
    "180000009ac2dcce90cabec4e6d464000c080000000a00000006"
)
POOLED_RESPONSE = bytes.fromhex(
    "04a0b4c3deffffff7f8cbf100165658e1ffe3aa4b4e8d0030000000604000000030000000f100000"
    "000c0000004d616e6748655f62736a320024360000008c8ec2e6d0c2e0dedc98dee8e8cae4f2a4ca"
    "c6dee4c888c2e8c200000000005c000000020000000a0000008cdedce600400d030002205cd96428"
    "3ebe11180000009ac2dcce90cabec4e6d464000200000006"
)


def encode_doubled(text: str) -> bytes:
    return bytes(2 * value for value in text.encode("ascii") + b"\0")


def pooled_request(pool_id: str, page: int) -> bytes:
    encoded = encode_doubled(pool_id)
    request = bytearray(POOLED_REQUEST[:40])
    request[31:35] = (page * 2).to_bytes(4, "little")
    return (
        bytes(request)
        + (2 * len(encoded)).to_bytes(4, "little")
        + encoded
        + (2060).to_bytes(4, "little")
        + b"\0"
        + (10).to_bytes(4, "little")
        + b"\x06"
    )


def pooled_response(pool_id: str, records: list[tuple[str, int, datetime]]) -> bytes:
    pool = pool_id.encode("ascii") + b"\0"
    body = bytearray()
    for reward_id, quantity, timestamp in records:
        encoded_id = reward_id.encode("utf-8") + b"\0"
        ticks = int(timestamp.timestamp() * 10_000_000) + 621_355_968_000_000_000
        body += len(encoded_id).to_bytes(4, "little") + encoded_id
        body += quantity.to_bytes(4, "little") + b"\x01" + ticks.to_bytes(8, "little")
        body += len(pool).to_bytes(4, "little") + pool + (1).to_bytes(4, "little")
    return (
        bytes(50)
        + MYSTERY_BOX_MARKER
        + b"\0"
        + bytes(4)
        + (len(body) + 4).to_bytes(4, "little")
        + len(records).to_bytes(4, "little")
        + body
        + b"\x03"
    )


class MysteryBoxDecodingTests(unittest.TestCase):
    def test_recognizes_request_and_page_cursor(self):
        request = mystery_box_request(6)
        self.assertTrue(is_mystery_box_history_request(request))
        self.assertEqual(mystery_box_request_page(request), 6)

    def test_recognizes_pooled_request_from_v1_4_capture(self):
        self.assertTrue(is_mystery_box_history_request(POOLED_REQUEST))
        self.assertEqual(mystery_box_request_page(POOLED_REQUEST), 1)

    def test_rejects_pooled_request_with_wrong_trailer(self):
        request = bytearray(POOLED_REQUEST)
        request[-5] = 0
        self.assertFalse(is_mystery_box_history_request(bytes(request)))

    def test_decodes_pooled_response_from_v1_4_capture(self):
        rows = parse_mystery_box_response(POOLED_RESPONSE)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reward_id"], "Fons")
        self.assertEqual(rows[0]["quantity"], 100_000)
        self.assertEqual(rows[0]["structured_pool_id"], "MangHe_bsj2")
        self.assertEqual(rows[0]["timestamp_decoded"], "2026-09-30 16:59:31")

    def test_live_session_pairs_pooled_request_and_response(self):
        session = LiveHistorySession("192.168.0.10")
        session.process_packet(
            UdpPacket(1.0, "192.168.0.10", "203.0.113.5", 50000, 40000, POOLED_REQUEST)
        )
        self.assertTrue(
            session.process_packet(
                UdpPacket(1.1, "203.0.113.5", "192.168.0.10", 40000, 50000, POOLED_RESPONSE)
            )
        )
        self.assertEqual(session.kinds_seen(), ["mystery_box:MangHe_bsj2"])

    def test_live_session_keeps_each_pool_as_separate_history(self):
        session = LiveHistorySession("192.168.0.10")
        timestamp = datetime(2026, 9, 30, 16, 59, 31, tzinfo=timezone.utc)
        client = ("192.168.0.10", "203.0.113.5", 50000, 40000)
        server = ("203.0.113.5", "192.168.0.10", 40000, 50000)
        for index, (pool_id, reward_id) in enumerate(
            [("MangHe_bsj2", "Fons"), ("MangHe_bsj", "gold")]
        ):
            session.process_packet(UdpPacket(index, *client, pooled_request(pool_id, 1)))
            session.process_packet(
                UdpPacket(
                    index + 0.5,
                    *server,
                    pooled_response(pool_id, [(reward_id, 100_000, timestamp)]),
                )
            )

        self.assertEqual(
            session.kinds_seen(), ["mystery_box:MangHe_bsj2", "mystery_box:MangHe_bsj"]
        )
        self.assertEqual(
            session.build_rows("mystery_box:MangHe_bsj2")[0]["reward_id"], "Fons"
        )
        self.assertEqual(session.build_rows("mystery_box:MangHe_bsj")[0]["reward_id"], "Gold")
        self.assertEqual(session.export_kinds(), ["mystery_box"])
        rows, warnings, pages_seen, pools = collect_export_rows(session, "mystery_box")
        export = build_export_json(rows, warnings, pages_seen=pages_seen, pools=pools)
        self.assertEqual(
            [record["pool_id"] for record in export["records"]], ["MangHe_bsj2", "MangHe_bsj"]
        )
        self.assertEqual(
            export["scan"]["pools"],
            [
                {"pool_id": "MangHe_bsj2", "pages_seen": [1], "exported_records": 1},
                {"pool_id": "MangHe_bsj", "pages_seen": [1], "exported_records": 1},
            ],
        )

    def test_decodes_exact_quantity_and_timestamp(self):
        timestamp = datetime(2026, 7, 8, 19, 9, 33, tzinfo=timezone.utc)
        rows = parse_mystery_box_response(
            mystery_box_response(
                [
                    ("vehicle039", 1, timestamp),
                    ("SpecialGift_ticket", 3, timestamp),
                    ("gold", 100_000, timestamp),
                ]
            )
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["reward_id"], "vehicle039")
        self.assertEqual(rows[0]["reward_name"], "Draco")
        self.assertEqual(rows[0]["timestamp_decoded"], "2026-07-08 19:09:33")
        self.assertEqual(rows[1]["quantity"], 3)
        self.assertEqual(rows[1]["result_type"], "single_pull")
        self.assertEqual(rows[2]["reward_name"], "Beetle Coin")
        self.assertEqual(rows[2]["reward_rank"], "B")

    def test_reward_mapping_lookup_is_case_insensitive_and_canonical(self):
        timestamp = datetime(2026, 7, 8, 19, 9, 33, tzinfo=timezone.utc)
        rows = parse_mystery_box_response(
            mystery_box_response([("Vehicle039", 1, timestamp)])
        )

        self.assertEqual(rows[0]["reward_id"], "vehicle039")
        self.assertEqual(rows[0]["reward_name"], "Draco")

    def test_live_session_accepts_partial_final_page(self):
        session = LiveHistorySession("192.168.0.10")
        request = mystery_box_request(3)
        timestamp = datetime(2026, 7, 8, 19, 9, 33, tzinfo=timezone.utc)
        response = mystery_box_response(
            [("Fons", 100_000, timestamp), ("gold", 100_000, timestamp)]
        )
        self.assertFalse(
            session.process_packet(
                UdpPacket(1.0, "192.168.0.10", "203.0.113.5", 50000, 40000, request)
            )
        )
        self.assertTrue(
            session.process_packet(
                UdpPacket(1.1, "203.0.113.5", "192.168.0.10", 40000, 50000, response)
            )
        )
        self.assertEqual(session.kinds_seen(), ["mystery_box"])
        self.assertEqual(session.pairs[0][0], 3)
        self.assertEqual(session.pairs[0][8:10], (0, 2))

    def test_rows_and_export_use_non_shared_mystery_box_banner(self):
        timestamp = datetime(2026, 7, 8, 19, 9, 33, tzinfo=timezone.utc)
        response = mystery_box_response([("Fons", 100_000, timestamp)])
        rows = build_mystery_box_rows_from_pairs(
            [(1, 2, 1, 1.0, 2, 1.1, response, "mystery_box", 0, 1)]
        )
        export = build_export_json(rows, [])
        self.assertEqual(export["banner"]["id"], "Gashapon_MysteryBox")
        self.assertEqual(export["banner"]["name"], "Mystery Box")
        self.assertIs(export["banner"]["shared_pity"], False)
        self.assertEqual(export["records"][0]["result_type"], "single_pull")
        self.assertEqual(export["records"][0]["quantity"], 100_000)
        self.assertNotIn("roll_result", export["records"][0])
        self.assertEqual(rows[0]["timestamp_group_size_seen"], 1)
        self.assertEqual(rows[0]["uid_status"], "stable")

    def test_export_path_uses_mystery_box_prefix(self):
        _csv_path, json_path = export_paths("mystery_box", "218216016349")
        self.assertRegex(
            json_path.name,
            r"^218216016349_MysteryBox_\d{8}_\d{6}(?:_\d+)?\.json$",
        )
