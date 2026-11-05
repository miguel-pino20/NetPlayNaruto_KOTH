import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request

import updater

REPOSITORY = "example/netplay"
APPIMAGE = b"\x7fELF" + bytes(4) + b"AI\x02" + bytes(5) + b"test AppImage payload"
EXE = b"MZ" + bytes(14) + b"test Windows payload"


def entry(tag, platform="linux", prerelease=True):
    name = updater.release_info.ASSET_NAMES[platform]
    base = f"https://github.com/{REPOSITORY}/releases/download/{tag}/"
    return {"tag_name": tag, "prerelease": prerelease, "draft": False, "assets": [
        {"name": name, "browser_download_url": base + name, "size": len(APPIMAGE)},
        {"name": name + ".sha256", "browser_download_url": base + name + ".sha256", "size": 100},
    ]}


class ReleaseSelectionTests(unittest.TestCase):
    def choose(self, entries, platform="linux", include_prereleases=True):
        return updater.select_release(entries, "0.1.0A", platform, REPOSITORY, include_prereleases)

    def test_selects_newest_numbered_version_not_publication_order(self):
        result = self.choose([entry("0.1.2A"), entry("0.1.10A"), entry("0.1.9A"), entry("Alpha")])
        self.assertEqual(result.version, "0.1.10A")

    def test_same_older_or_draft_releases_do_not_update(self):
        draft = entry("9.0.0")
        draft["draft"] = True
        self.assertIsNone(self.choose([entry("0.1.0A"), entry("0.0.9"), draft]))

    def test_numeric_and_prerelease_order(self):
        versions = ["0.1.1A", "v0.1.1-alpha.1", "0.1.1-beta.1", "0.1.1-rc.1", "0.1.1", "0.1.2A"]
        self.assertEqual(sorted(versions, key=updater.version_key), versions)

    def test_selects_only_assets_for_this_platform_and_requires_checksum(self):
        self.assertIsNone(self.choose([entry("0.1.1A", "windows")]))
        incomplete = entry("0.1.1A")
        incomplete["assets"].pop()
        self.assertIsNone(self.choose([incomplete]))
        self.assertEqual(self.choose([entry("0.1.1A", "windows")], "windows").asset_name,
                         "UN5-Netplay-Windows-x64.exe")

    def test_option_to_ignore_prereleases(self):
        self.assertIsNone(self.choose([entry("0.1.1A")], include_prereleases=False))
        self.assertEqual(self.choose([entry("0.1.1", prerelease=False)], include_prereleases=False).version,
                         "0.1.1")

    def test_untrusted_urls_incomplete_and_malformed_metadata_are_skipped(self):
        for url in ("http://github.com/example/netplay/releases/download/v1/app", "https://evil.test/app",
                    "https://github.com/other/repo/releases/download/v1/app", None):
            bad = entry("0.1.1A")
            bad["assets"][0]["browser_download_url"] = url
            self.assertIsNone(self.choose([bad]))
        self.assertIsNone(self.choose([{"tag_name": "0.1.1A", "assets": None}, None]))

    def test_redirects_never_downgrade_tls_or_leave_github(self):
        handler = updater.GithubRedirects()
        for url in ("http://release-assets.githubusercontent.com/file", "https://evil.test/file"):
            with self.assertRaises(updater.UpdateError):
                handler.redirect_request(Request("https://github.com/example"), None, 302, "Found", {}, url)


class DownloadAndInstallTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.target = self.root / "Netplay con espacios.AppImage"
        self.target.write_bytes(b"previous working version")
        self.stage = self.root / ".un5-update-test"
        self.stage.mkdir()
        self.release = updater.select_release([entry("0.1.1A")], "0.1.0A", "linux", REPOSITORY)
        self.digest = hashlib.sha256(APPIMAGE).hexdigest()

    def responses(self, payload=APPIMAGE, digest=None):
        checksum = f"{digest or self.digest}  {self.release.asset_name}\n".encode()
        return [io.BytesIO(checksum), io.BytesIO(payload)]

    def test_download_checks_size_hash_and_appimage_before_installing(self):
        progress = Mock()
        with patch.object(updater, "_response", side_effect=self.responses()):
            payload, digest = updater.download_release(self.release, self.stage, "linux", progress,
                                                       threading.Event())
        self.assertEqual(payload.read_bytes(), APPIMAGE)
        self.assertEqual(digest, self.digest)
        self.assertEqual(self.target.read_bytes(), b"previous working version")
        progress.assert_called()

    def test_corrupt_incomplete_or_wrong_format_download_never_changes_old_binary(self):
        variants = [(APPIMAGE[:-1], self.digest), (APPIMAGE, "0" * 64), (b"x" * len(APPIMAGE),
                     hashlib.sha256(b"x" * len(APPIMAGE)).hexdigest())]
        for payload, digest in variants:
            with self.subTest(digest=digest), tempfile.TemporaryDirectory(dir=self.root) as stage, \
                    patch.object(updater, "_response", side_effect=self.responses(payload, digest)):
                with self.assertRaises(updater.UpdateError):
                    updater.download_release(self.release, Path(stage), "linux", Mock(), threading.Event())
                self.assertEqual(self.target.read_bytes(), b"previous working version")

    def test_checksum_must_name_exact_platform_file(self):
        with self.assertRaises(updater.UpdateError):
            updater.parse_checksum(f"{self.digest}  other.exe\n".encode(), self.release.asset_name)

    def test_cancelled_download_never_installs(self):
        cancelled = threading.Event()
        cancelled.set()
        with patch.object(updater, "_response", side_effect=self.responses()):
            with self.assertRaises(updater.Cancelled):
                updater.download_release(self.release, self.stage, "linux", Mock(), cancelled)
        self.assertEqual(self.target.read_bytes(), b"previous working version")

    def test_atomic_install_preserves_path_and_previous_version_until_new_window_opens(self):
        payload = self.stage / "payload.AppImage"
        payload.write_bytes(APPIMAGE)
        with patch.object(updater, "start_binary") as restart:
            updater.schedule_install(self.target, payload, self.digest, self.stage, "linux")
        self.assertEqual(self.target.read_bytes(), APPIMAGE)
        self.assertEqual((self.stage / "previous").read_bytes(), b"previous working version")
        restart.assert_called_once_with(self.target, self.stage)
        self.assertTrue(os.access(self.target, os.X_OK))

    def test_restart_failure_rolls_back_original_binary(self):
        payload = self.stage / "payload.AppImage"
        payload.write_bytes(APPIMAGE)
        with patch.object(updater, "start_binary", side_effect=OSError("cannot start")):
            with self.assertRaises(OSError):
                updater.schedule_install(self.target, payload, self.digest, self.stage, "linux")
        self.assertEqual(self.target.read_bytes(), b"previous working version")

    def test_windows_schedules_separate_helper_before_replacing_locked_executable(self):
        target = self.root / "UN5 Netplay.exe"
        target.write_bytes(EXE)
        payload = self.stage / "payload.exe"
        payload.write_bytes(EXE)
        with patch.object(updater.subprocess, "Popen") as spawn:
            updater.schedule_install(target, payload, hashlib.sha256(EXE).hexdigest(), self.stage, "windows")
        self.assertEqual(target.read_bytes(), EXE)
        self.assertTrue(payload.is_file())
        self.assertEqual((self.stage / "update-helper.exe").read_bytes(), EXE)
        self.assertEqual(spawn.call_args.args[0][1], "--apply-update")
        self.assertEqual(json.loads((self.stage / "request.json").read_text())["target"], str(target))
        self.assertEqual(spawn.call_args.kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")

    def test_restart_clears_old_mount_environment(self):
        with patch.dict(os.environ, {"APPIMAGE": "/old.AppImage", "TCL_LIBRARY": "/old/tcl", "_PYI_ARCHIVE_FILE": "old"}):
            env = updater.restart_environment(self.stage)
        self.assertNotIn("APPIMAGE", env)
        self.assertNotIn("TCL_LIBRARY", env)
        self.assertNotIn("_PYI_ARCHIVE_FILE", env)
        self.assertEqual(env["UN5_SKIP_RELEASE_CHECK_ONCE"], "1")

    def test_restart_skips_one_network_check(self):
        with patch.dict(os.environ, {"UN5_SKIP_RELEASE_CHECK_ONCE": "1"}), \
                patch.object(updater, "find_update") as check:
            self.assertFalse(updater.check_for_updates_on_startup())
            self.assertNotIn("UN5_SKIP_RELEASE_CHECK_ONCE", os.environ)
            check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
