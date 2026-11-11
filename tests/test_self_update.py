import hashlib
import io
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from nte_history_exporter.gui import self_update, theme
from nte_history_exporter.gui.app import Bridge
from nte_history_exporter.update_check import (
    RELEASE_DOWNLOAD_URL,
    ReleaseAsset,
    UpdateInfo,
    check_for_update,
)

DATA = b"new build" * 1000


def make_asset(data=DATA, **overrides):
    fields = {
        "name": "nte-history-exporter-gui.exe",
        "url": f"{RELEASE_DOWNLOAD_URL}v9.0.0/nte-history-exporter-gui.exe",
        "size": len(data),
        "digest": f"sha256:{hashlib.sha256(data).hexdigest()}",
    }
    return ReleaseAsset(**{**fields, **overrides})


def make_update(*assets):
    return UpdateInfo("0.4.0", "v9.0.0", "https://example.invalid/release", assets)


class AssetSelectionTests(unittest.TestCase):
    def test_every_platform_names_a_file_the_release_publishes(self):
        workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
        for platform in ("win32", "linux", "darwin"):
            with self.subTest(platform), patch.object(self_update.sys, "platform", platform):
                name = self_update.asset_name("v0.5.0").replace("0.5.0", "${version}")
                self.assertIn(name, workflow)

    def test_source_runs_never_self_update(self):
        self.assertIsNone(self_update.current_install())
        self.assertIsNone(self_update.find_asset(make_update(make_asset())))

    def test_missing_platform_file_means_no_update(self):
        with (
            patch.object(self_update, "current_install", return_value=Path("app.exe")),
            patch.object(self_update, "asset_name", return_value="wanted"),
        ):
            self.assertIsNone(self_update.find_asset(make_update(make_asset(name="other"))))
            wanted = make_asset(name="wanted")
            self.assertEqual(self_update.find_asset(make_update(wanted)), wanted)

    def test_a_macos_install_is_the_app_bundle(self):
        with (
            patch.object(self_update.sys, "frozen", True, create=True),
            patch.object(self_update.sys, "platform", "darwin"),
            patch.object(self_update.sys, "executable", "/Applications/X.app/Contents/MacOS/x"),
            patch.object(Path, "resolve", lambda path: path),
        ):
            self.assertEqual(self_update.current_install().name, "X.app")

    def test_update_check_carries_the_release_files(self):
        latest = {
            "tag_name": "v9.0.0",
            "html_url": "https://example.invalid/",
            "assets": [
                {"name": "a", "browser_download_url": "https://x/a", "size": 3, "digest": "sha256:ab"},
                {"name": "no url"},
            ],
        }
        with patch("nte_history_exporter.update_check.fetch_latest_release", return_value=latest):
            update = check_for_update("0.4.0")
        self.assertEqual(update.assets, (ReleaseAsset("a", "https://x/a", 3, "sha256:ab"),))


class DownloadTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.target = Path(tmp.name) / "app.exe"

    def fetch(self, asset, data=DATA):
        seen = []
        with patch.object(self_update.urllib.request, "urlopen", return_value=io.BytesIO(data)) as urlopen:
            path = self_update.download(asset, self.target, seen.append)
        return path, seen, urlopen

    def test_verified_download_lands_beside_the_target(self):
        path, seen, _ = self.fetch(make_asset())
        self.assertEqual(path.read_bytes(), DATA)
        self.assertEqual(path.parent, self.target.parent)
        self.assertEqual(seen[-1], 100)

    def test_bad_checksum_is_rejected_and_removed(self):
        with self.assertRaises(self_update.UpdateError):
            self.fetch(make_asset(), data=b"tampered")
        self.assertEqual(list(self.target.parent.iterdir()), [])

    def test_only_this_repos_releases_are_fetched(self):
        with self.assertRaises(self_update.UpdateError), patch.object(
            self_update.urllib.request, "urlopen"
        ) as urlopen:
            self_update.download(make_asset(url="https://example.invalid/x.exe"), self.target, print)
        urlopen.assert_not_called()

    def test_a_release_without_a_checksum_is_refused(self):
        for digest in ("", "md5:abc", "sha256:short"):
            with self.subTest(digest), self.assertRaises(self_update.UpdateError):
                self.fetch(make_asset(digest=digest))


class InstallTests(unittest.TestCase):
    def setUp(self):
        # These cover the plain-executable swap. On a real Mac install() would unzip
        # the download as a .app with ditto, which these placeholder files aren't.
        platform = patch.object(self_update.sys, "platform", "linux")
        platform.start()
        self.addCleanup(platform.stop)
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.target = Path(tmp.name) / "app.exe"
        self.target.write_text("old")
        self.downloaded = Path(tmp.name) / "app.exe.download"
        self.downloaded.write_text("new")

    def test_swaps_the_build_and_starts_the_new_one(self):
        with patch.object(self_update.subprocess, "Popen") as popen:
            self_update.install(self.downloaded, self.target)

        self.assertEqual(self.target.read_text(), "new")
        self.assertEqual(self.target.with_name("app.exe.old").read_text(), "old")
        self.assertEqual(popen.call_args.args[0], [str(self.target)])
        self.assertEqual(popen.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_old_build_returns_if_the_new_one_will_not_start(self):
        with (
            patch.object(self_update.subprocess, "Popen", side_effect=OSError("blocked")),
            self.assertRaises(OSError),
        ):
            self_update.install(self.downloaded, self.target)

        self.assertEqual(self.target.read_text(), "old")
        self.assertFalse(self.target.with_name("app.exe.old").exists())

    def test_leftovers_are_removed_on_the_next_start(self):
        self.target.with_name("app.exe.old").write_text("old")
        with patch.object(self_update, "current_install", return_value=self.target):
            self_update.remove_leftovers(attempts=1)
        self.assertEqual(sorted(path.name for path in self.target.parent.iterdir()), ["app.exe"])


class BridgeUpdateTests(unittest.TestCase):
    def setUp(self):
        self.bridge = Bridge()
        self.bridge.events.put(("update", make_update(make_asset())))

    def ops(self, name):
        return [op for op in self.bridge.poll() if op["op"] == name]

    def click(self, **install):
        with (
            patch.object(self_update, "find_asset", return_value=make_asset()),
            patch.object(self_update, "current_install", return_value=Path("app.exe")),
            patch.object(self_update, "download", return_value=Path("app.exe.download")),
            patch.object(self_update, "install", **install) as installer,
            patch.object(self.bridge, "_close_window") as close,
            patch("nte_history_exporter.gui.app.webbrowser.open") as browser,
        ):
            self.bridge.open_update()
            self._join_workers()
            ops = self.bridge.poll()
        return ops, installer, close, browser

    def _join_workers(self):
        for thread in threading.enumerate():
            if thread is not threading.current_thread() and thread.name.endswith("(_run_update)"):
                thread.join(5)

    def test_runs_from_source_open_the_release_page(self):
        self.assertTrue(self.ops("update")[0]["text"].startswith("Update available"))
        with patch("nte_history_exporter.gui.app.webbrowser.open") as browser:
            self.bridge.open_update()
        browser.assert_called_once_with("https://example.invalid/release")

    def test_success_closes_this_window(self):
        self.bridge.poll()
        ops, installer, close, _ = self.click()
        installer.assert_called_once()
        close.assert_called_once()
        self.assertEqual(self.bridge._updating, True)
        self.assertEqual([op["text"] for op in ops if op["op"] == "update"][-1], theme.TEXT["update_installing"])

    def test_failure_keeps_the_app_open_and_shows_the_release_page(self):
        self.bridge.poll()
        ops, _, close, browser = self.click(side_effect=PermissionError("Access is denied"))
        close.assert_not_called()
        browser.assert_called_once_with("https://example.invalid/release")
        self.assertFalse(self.bridge._updating)
        logged = [op["segments"][0][0] for op in ops if op["op"] == "log"]
        self.assertIn("Access is denied", logged[0])
        self.assertFalse([op for op in ops if op["op"] == "update"][-1]["busy"])

    def test_waits_for_a_running_capture(self):
        self.bridge.poll()
        release = threading.Event()
        self.bridge._worker = threading.Thread(target=release.wait, daemon=True)
        self.bridge._worker.start()
        self.addCleanup(release.set)

        ops, installer, _, _ = self.click()
        installer.assert_not_called()
        self.assertFalse(self.bridge._updating)
        self.assertEqual(ops[0]["segments"][0][0], theme.TEXT["update_blocked"])

    def test_no_capture_starts_during_an_update(self):
        self.bridge.poll()
        self.bridge._updating = True
        self.bridge.start_capture({})
        self.assertIsNone(self.bridge._worker)
