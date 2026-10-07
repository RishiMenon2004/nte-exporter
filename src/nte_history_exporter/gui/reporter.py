from __future__ import annotations

import queue
import threading


class PromptReply:
    """A question the capture thread is blocked on until the window answers it."""

    def __init__(self) -> None:
        self.value: str | None = None
        self._answered = threading.Event()

    def answer(self, value: str | None) -> None:
        self.value = value
        self._answered.set()

    def wait(self) -> str | None:
        self._answered.wait()
        return self.value


class GuiReporter:
    """Stands in for the ``console`` module while the runner works on a background thread.

    Tk widgets may only be touched from the main thread, so each call is turned
    into an event tuple ``(name, *args)`` on a queue that the window drains.
    """

    def __init__(self, events: queue.Queue) -> None:
        self._events = events

    def _emit(self, *event) -> None:
        self._events.put(event)

    def _log(self, text: str, tag: str = "info") -> None:
        self._emit("log", text, tag)

    def print_live_instructions(self, local_ip: str, backend: str = "windows_raw", detail: str = "") -> None:
        self._emit("listening", local_ip, backend, detail)

    def print_capture_fallback(self, reason: str) -> None:
        self._log("Npcap unavailable; using Windows raw capture.", "warning")
        self._log(reason, "muted")
        self._log("Raw capture may require running as Administrator.", "muted")

    def print_achievements_captured(
        self,
        in_game_completed: int,
        in_game_in_progress: int,
        playstation_completed: int,
        playstation_in_progress: int,
    ) -> None:
        self._emit(
            "achievements",
            in_game_completed,
            in_game_in_progress,
            playstation_completed,
            playstation_in_progress,
        )

    def print_page_captured(self, label: str, page: int | None, *, recaptured: bool = False) -> None:
        self._emit("page", label, page, recaptured)

    def print_missing_pages(self, label: str, pages: list[int]) -> None:
        self._emit("missing", label, pages)

    def print_page_gap_recovered(self, label: str) -> None:
        self._emit("recovered", label)

    def print_capture_stats(self, received: int, dropped: int, interface_dropped: int) -> None:
        text = (
            f"Capture stats: processed {received}, buffer dropped {dropped}, "
            f"interface dropped {interface_dropped}"
        )
        self._log(text, "warning" if dropped or interface_dropped else "muted")

    def print_results_header(self) -> None:
        self._emit("results")

    def print_export_summary(self, name: str, decoded: int, exported: int, skipped: int) -> None:
        self._emit("summary", name, decoded, exported, skipped)

    def print_warning(self, code: str, reason: str, records: int | None = None) -> None:
        suffix = f" ({records} records)" if records is not None else ""
        self._log(f"! {code}: {reason}{suffix}", "warning")

    def print_blank(self) -> None:
        self._log("")

    def print_note(self, text: str) -> None:
        self._log(text, "muted")

    def print_success(self, text: str) -> None:
        self._log(text, "success")

    def print_problem(self, text: str) -> None:
        self._log(text, "warning")

    def prompt_user_uid(self) -> str | None:
        return self._ask("user_uid")

    def prompt_server_id(self) -> str | None:
        return self._ask("server_id")

    def _ask(self, kind: str) -> str | None:
        reply = PromptReply()
        self._emit("prompt", kind, reply)
        return reply.wait()
