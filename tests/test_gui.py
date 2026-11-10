import json
import os
import queue
import re
import threading

from tests.support import *  # noqa: F401,F403
from nte_history_exporter.gui import theme, trackers
from nte_history_exporter.gui.app import Bridge, format_pages
from nte_history_exporter.gui.reporter import GuiReporter, PromptReply
from nte_history_exporter.live_capture.runner import run_live_capture


def drain(events: queue.Queue) -> list[tuple]:
    items = []
    while not events.empty():
        items.append(events.get_nowait())
    return items


class IdleCapture:
    name = "npcap"
    detail = r"\Device\NPF_test"
    fallback_reason = ""

    def __init__(self):
        self.closed = False

    def packets(self):
        while True:
            yield None

    def stats(self):
        return None

    def close(self):
        self.closed = True


class GuiReporterTests(unittest.TestCase):
    def test_runner_stops_on_callback_and_reports_through_queue(self):
        events = queue.Queue()
        capture = IdleCapture()
        polls = []

        def stop_requested():
            polls.append(None)
            return len(polls) >= 3

        with patch(
            "nte_history_exporter.live_capture.runner.open_capture_backend",
            return_value=capture,
        ):
            result = run_live_capture(
                interface_ip="192.0.2.1",
                reporter=GuiReporter(events),
                stop_requested=stop_requested,
            )

        self.assertTrue(capture.closed)
        self.assertEqual(result["exports"], [])
        self.assertEqual(len(polls), 3)
        names = [event[0] for event in drain(events)]
        self.assertEqual(names[0], "listening")
        self.assertIn("results", names)

    def test_runner_reports_no_pages_problem(self):
        events = queue.Queue()
        with patch(
            "nte_history_exporter.live_capture.runner.open_capture_backend",
            return_value=IdleCapture(),
        ):
            run_live_capture(interface_ip="192.0.2.1", reporter=GuiReporter(events), stop_requested=lambda: True)

        self.assertIn(("log", "No history pages were captured.", "warning"), drain(events))

    def test_prompt_blocks_until_answered(self):
        events = queue.Queue()
        reporter = GuiReporter(events)
        answers = []
        worker = threading.Thread(target=lambda: answers.append(reporter.prompt_server_id()))
        worker.start()

        name, kind, reply = events.get(timeout=2)
        self.assertEqual((name, kind), ("prompt", "server_id"))
        self.assertTrue(worker.is_alive())
        reply.answer("23003")
        worker.join(timeout=2)

        self.assertEqual(answers, ["23003"])

    def test_page_only_uses_defined_text_keys(self):
        from nte_history_exporter.gui import app, theme

        page = (app.WEB_DIR / "index.html").read_text(encoding="utf-8")
        script = (app.WEB_DIR / "app.js").read_text(encoding="utf-8")
        keys = set(re.findall(r'data-text="(\w+)"', page)) | set(re.findall(r"TEXT\.(\w+)", script))
        self.assertTrue(keys)
        self.assertEqual(keys - set(theme.TEXT), set())

    def test_working_dir_moves_only_when_needed(self):
        from nte_history_exporter.gui import app

        with TemporaryDirectory() as tmp:
            # Resolve symlinks: on macOS the temp dir is under /var -> /private/var,
            # and Path.cwd() reports the resolved path.
            home = Path(tmp).resolve()
            start = Path.cwd()
            try:
                with patch.object(app.Path, "home", return_value=home):
                    with patch.object(app.sys, "platform", "win32"), patch.object(app.os, "access", return_value=True):
                        app._use_writable_working_dir()
                        self.assertEqual(Path.cwd(), start)

                    with patch.object(app.sys, "platform", "linux"), patch.object(app.os, "access", return_value=False):
                        app._use_writable_working_dir()
                        self.assertEqual(Path.cwd(), home / "NTE History Exporter")

                    with patch.object(app.sys, "platform", "darwin"), patch.object(app.sys, "frozen", True, create=True):
                        app._use_writable_working_dir()
                        self.assertEqual(Path.cwd(), home / "Documents" / "NTE History Exporter")
            finally:
                os.chdir(start)

    def test_format_pages_collapses_ranges(self):
        self.assertEqual(format_pages({1, 2, 3, 5, 7, 8}), "1-3, 5, 7-8")
        self.assertEqual(format_pages({4}), "4")
        self.assertEqual(format_pages(set()), "")


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.bridge = Bridge()

    def ops(self, *names):
        for event in names:
            self.bridge.events.put(event)
        return self.bridge.poll()

    def test_rows_collect_pages_and_keep_a_gap_warning(self):
        self.ops(("page", "Arc Miracle Box", 1, False), ("page", "Arc Miracle Box", 2, False))
        self.ops(("missing", "Arc Miracle Box", [3]))
        rows = [op for op in self.ops(("page", "Arc Miracle Box", 4, False)) if op["op"] == "row"]

        self.assertEqual(
            rows,
            [
                {
                    "op": "row",
                    "label": "Arc Miracle Box",
                    "pages": "1-2, 4",
                    "status": "Missing page(s) 3",
                    "tag": "warning",
                }
            ],
        )

        recovered = [op for op in self.ops(("recovered", "Arc Miracle Box")) if op["op"] == "row"]
        self.assertEqual((recovered[0]["status"], recovered[0]["tag"]), ("Gap recovered", "success"))

    def test_prompt_answer_reaches_the_waiting_reply(self):
        reply = PromptReply()
        dialog = self.ops(("prompt", "server_id", reply))[0]

        self.assertEqual((dialog["op"], dialog["kind"]), ("dialog", "prompt"))
        self.assertTrue(dialog["choices"])
        self.bridge.answer_prompt(dialog["id"], " 23003 ")
        self.assertEqual(reply.wait(), "23003")

        skipped = PromptReply()
        dialog = self.ops(("prompt", "user_uid", skipped))[0]
        self.assertIsNone(dialog["choices"])
        self.bridge.answer_prompt(dialog["id"], None)
        self.assertIsNone(skipped.wait())

    def test_clipboard_copy_only_for_a_single_export(self):
        self.bridge._copy_after_capture = True
        finished = lambda count: ("finished", {"exports": [{"payload": "{}"}] * count, "achievement_path": None})

        self.assertIn({"op": "copy", "text": "{}"}, self.ops(finished(1)))
        self.assertFalse([op for op in self.ops(finished(2)) if op["op"] == "copy"])

    def test_closing_during_capture_asks_first(self):
        release = threading.Event()
        self.bridge._worker = threading.Thread(target=release.wait, daemon=True)
        self.bridge._worker.start()
        self.addCleanup(release.set)

        self.assertFalse(self.bridge._on_window_closing())
        dialogs = [op for op in self.bridge.poll() if op["op"] == "dialog"]
        self.assertEqual([dialog["kind"] for dialog in dialogs], ["close"])

        self.bridge.resolve_close("save")
        self.assertTrue(self.bridge._stop_event.is_set())
        self.assertFalse(self.bridge._on_window_closing())
        self.assertFalse([op for op in self.bridge.poll() if op["op"] == "dialog"])

    def test_closing_while_idle_is_allowed(self):
        self.assertTrue(self.bridge._on_window_closing())

    def test_tracker_buttons_open_only_configured_sites(self):
        keys = [site["key"] for site in self.bridge.bootstrap()["trackers"]]
        self.assertEqual(keys, list(trackers.SITES))

        with (
            patch("nte_history_exporter.gui.app.webbrowser.open") as opened,
            patch("nte_history_exporter.gui.app.exports_folder_is_open", return_value=True),
        ):
            self.bridge.open_tracker("chiz_pink")
            self.bridge.open_tracker("https://example.invalid/")

        opened.assert_called_once_with(trackers.SITES["chiz_pink"]["url"])

    def test_tracker_button_opens_the_exports_folder_only_if_needed(self):
        order = []
        with (
            patch("nte_history_exporter.gui.app.webbrowser.open", side_effect=lambda url: order.append("browser")),
            patch("nte_history_exporter.gui.app.exports_folder_is_open", return_value=False),
            patch("nte_history_exporter.gui.app.time.sleep"),
            patch.object(self.bridge, "open_exports", side_effect=lambda: order.append("folder")),
        ):
            self.bridge.open_tracker("chiz_pink")
        self.assertEqual(order, ["browser", "folder"])

        with (
            patch("nte_history_exporter.gui.app.webbrowser.open"),
            patch("nte_history_exporter.gui.app.exports_folder_is_open", return_value=True),
            patch.object(self.bridge, "open_exports") as folder,
        ):
            self.bridge.open_tracker("chiz_pink")
        folder.assert_not_called()

    def test_tracker_still_opens_if_the_folder_cannot(self):
        with (
            patch("nte_history_exporter.gui.app.webbrowser.open") as browser,
            patch("nte_history_exporter.gui.app.exports_folder_is_open", return_value=False),
            patch("nte_history_exporter.gui.app.time.sleep"),
            patch.object(self.bridge, "open_exports", side_effect=OSError("no file manager")),
        ):
            self.bridge.open_tracker("chiz_pink")
        browser.assert_called_once()

    def test_tracker_opens_an_uploaded_drop_without_the_folder(self):
        with (
            patch("nte_history_exporter.gui.app.webbrowser.open") as browser,
            patch("nte_history_exporter.gui.app.exports_folder_is_open") as folder_check,
        ):
            self.bridge.open_tracker("chiz_pink", "drop-id.secret-key")

        open_url = trackers.SITES["chiz_pink"]["drop"]["open_url"]
        browser.assert_called_once_with(f"{open_url}#drop-id.secret-key")
        folder_check.assert_not_called()
        logged = [op for op in self.bridge.poll() if op["op"] == "log"]
        self.assertEqual(logged[0]["segments"][0][1], "success")

    def test_failed_drop_reports_why(self):
        self.bridge.report_drop_failed("chiz_pink", "HTTP 413")
        logged = [op for op in self.bridge.poll() if op["op"] == "log"]
        self.assertIn("HTTP 413", logged[0]["segments"][0][0])

    def test_import_drop_holds_every_export_from_the_latest_capture(self):
        self.assertIsNone(self.bridge.import_drop("chiz_pink"))

        exports = [{"payload": '{\n  "banner": {"id": "a"}\n}'}, {"payload": '{"banner": {"id": "é"}}'}]
        self.ops(("finished", {"exports": exports, "achievement_path": None}))
        drop = self.bridge.import_drop("chiz_pink")

        self.assertEqual(drop["upload_url"], trackers.SITES["chiz_pink"]["drop"]["upload_url"])
        self.assertEqual(drop["plaintext"], '{"version":1,"exports":[{"banner":{"id":"a"}},{"banner":{"id":"é"}}]}')

    def test_mystery_box_exports_are_not_sent_to_chiz_pink(self):
        limited = {"payload": '{"banner": {"id": "Lottery_LimitedCharacter"}}'}
        mystery = {"payload": '{"banner": {"id": "Gashapon_MysteryBox"}}'}

        self.ops(("finished", {"exports": [mystery, limited], "achievement_path": None}))
        exports = json.loads(self.bridge.import_drop("chiz_pink")["plaintext"])["exports"]
        self.assertEqual([export["banner"]["id"] for export in exports], ["Lottery_LimitedCharacter"])

        self.ops(("finished", {"exports": [mystery], "achievement_path": None}))
        self.assertIsNone(self.bridge.import_drop("chiz_pink"))

    def test_import_drop_is_only_for_sites_that_support_it(self):
        exports = [{"payload": '{"banner": {"id": "a"}}'}]
        self.ops(("finished", {"exports": exports, "achievement_path": None}))
        self.assertIsNone(self.bridge.import_drop("ntewiz"))
        self.assertIsNone(self.bridge.import_drop("https://example.invalid/"))

    def test_new_capture_clears_the_exports_to_send(self):
        self.ops(("finished", {"exports": [{"payload": "{}"}], "achievement_path": None}))
        with patch("nte_history_exporter.gui.app.run_live_capture", return_value={"exports": [], "achievement_path": None}):
            self.bridge.start_capture({})
            self.assertIsNone(self.bridge.import_drop("chiz_pink"))
            self.bridge._worker.join(5)

    def test_exports_folder_match_ignores_case_and_trailing_slash(self):
        from nte_history_exporter.gui import app

        with TemporaryDirectory() as tmp:
            exports = Path(tmp).resolve() / "exports"
            with patch.object(app, "EXPORT_DIR", exports):
                with patch.object(app, "open_explorer_folders", return_value=[str(exports).upper() + os.sep]):
                    self.assertEqual(app.exports_folder_is_open(), os.name == "nt")
                with patch.object(app, "open_explorer_folders", return_value=[str(exports) + "-old"]):
                    self.assertFalse(app.exports_folder_is_open())

    def test_failed_capture_shows_the_message(self):
        ops = self.ops(("failed", "Npcap not found.", "hint"))

        self.assertEqual(ops[0], {"op": "state", "state": "idle"})
        self.assertIn({"op": "status", "text": theme.TEXT["status_failed"]}, ops)
        self.assertEqual(ops[-1]["message"], "Npcap not found.")


if __name__ == "__main__":
    unittest.main()
