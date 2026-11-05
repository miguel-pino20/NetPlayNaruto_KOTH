"""Optional integration test: run with Windows Python after building the EXE."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import updater
from release_info import VERSION

EXE = Path(__file__).resolve().parent.parent / "dist/UN5-Netplay-Windows-x64.exe"


def launcher_windows(target):
    from ctypes import wintypes
    user = ctypes.windll.user32
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD))
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(window, _):
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(pid))
        handle = kernel.OpenProcess(0x1000, False, pid.value)
        if handle:
            try:
                size = wintypes.DWORD(32768)
                image = ctypes.create_unicode_buffer(size.value)
                if kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
                    if Path(image.value).resolve() == target.resolve() and user.IsWindowVisible(window):
                        title = ctypes.create_unicode_buffer(256)
                        user.GetWindowTextW(window, title, len(title))
                        if title.value == f"UN5 Netplay · {VERSION}":
                            found.append(window)
            finally:
                kernel.CloseHandle(handle)
        return True
    user.EnumWindows(visit, 0)
    return found


@unittest.skipUnless(sys.platform == "win32" and EXE.is_file(), "Requires Windows Python and the built EXE")
class WindowsUpdateIntegrationTests(unittest.TestCase):
    def test_offline_check_opens_installed_launcher_without_changing_exe(self):
        with tempfile.TemporaryDirectory(prefix="un5-offline-integration-") as folder:
            root = Path(folder)
            target = root / "Netplay sin conexión.exe"
            target.write_bytes(EXE.read_bytes())
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            env = {**os.environ, "APPDATA": str(root / "profile"), "HTTPS_PROXY": "http://127.0.0.1:1",
                   "HTTP_PROXY": "http://127.0.0.1:1", "NO_PROXY": ""}
            env.pop("UN5_SKIP_RELEASE_CHECK_ONCE", None)
            process = subprocess.Popen([str(target)], env=env)
            try:
                windows = []
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    windows = launcher_windows(target)
                    if windows:
                        break
                    time.sleep(0.2)
                self.assertTrue(windows, "The installed launcher did not open after the offline update check")
                self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), digest)
                log = root / "profile/UN5 Netplay/updater.log"
                self.assertIn("No se pudo actualizar", log.read_text(encoding="utf-8"))
            finally:
                for window in launcher_windows(target):
                    ctypes.windll.user32.PostMessageW(window, 0x0010, 0, 0)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=5)

    def test_helper_replaces_running_exe_restarts_gui_and_removes_backup(self):
        payload_bytes = EXE.read_bytes()
        digest = hashlib.sha256(payload_bytes).hexdigest()
        # Alter only the COFF timestamp: the old copy still runs, but has a different hash.
        old_bytes = bytearray(payload_bytes)
        pe_offset = int.from_bytes(old_bytes[0x3C:0x40], "little")
        old_bytes[pe_offset + 8] ^= 1
        with tempfile.TemporaryDirectory(prefix="un5-update-integration-") as folder:
            root = Path(folder)
            target = root / "Netplay prueba actualización.exe"
            target.write_bytes(old_bytes)
            stage = Path(tempfile.mkdtemp(prefix=updater.STAGE_PREFIX, dir=root))
            payload = stage / "payload.exe"
            payload.write_bytes(payload_bytes)
            with patch.dict(os.environ, {"APPDATA": str(root / "profile")}):
                old = subprocess.Popen([str(target), "--smoke-test-gui"])
                original_request = updater.write_request

                def request_for_running_exe(*args):
                    path = original_request(*args)
                    data = json.loads(path.read_text(encoding="utf-8"))
                    data["parent_pid"] = old.pid
                    path.write_text(json.dumps(data), encoding="utf-8")
                    return path

                try:
                    with patch.object(updater, "write_request", side_effect=request_for_running_exe):
                        helper = updater.schedule_install(target, payload, digest, stage, "windows")
                    self.assertEqual(old.wait(timeout=30), 0)
                    self.assertEqual(helper.wait(timeout=40), 0)
                    self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), digest)
                    windows = []
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        windows = launcher_windows(target)
                        if windows and not stage.exists():
                            break
                        time.sleep(0.2)
                    self.assertTrue(windows, "The updated launcher did not reopen")
                    self.assertFalse(stage.exists(), "The old binary was not cleaned up after the new window opened")
                finally:
                    for window in launcher_windows(target):
                        ctypes.windll.user32.PostMessageW(window, 0x0010, 0, 0)  # WM_CLOSE
                    if old.poll() is None:
                        old.terminate()
                    time.sleep(0.8)


if __name__ == "__main__":
    unittest.main()
