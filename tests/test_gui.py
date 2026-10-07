import os
import queue
import threading

from tests.support import *  # noqa: F401,F403
from nte_history_exporter.gui.app import format_pages
from nte_history_exporter.gui.reporter import GuiReporter
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

    def test_palette_choice_round_trips_and_falls_back(self):
        from nte_history_exporter.gui import app, theme

        with TemporaryDirectory() as tmp:
            prefs = Path(tmp) / "nested" / "gui.json"
            with patch.object(app, "PREFS_PATH", prefs):
                self.assertEqual(app.load_palette(), theme.PALETTE)
                app.save_palette("light")
                self.assertEqual(app.load_palette(), "light")
                prefs.write_text('{"palette": "no-such-palette"}', encoding="utf-8")
                self.assertEqual(app.load_palette(), theme.PALETTE)
                prefs.write_text("not json", encoding="utf-8")
                self.assertEqual(app.load_palette(), theme.PALETTE)

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


if __name__ == "__main__":
    unittest.main()
