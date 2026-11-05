"""Opt-in GUI/update test; uses a temporary AppImage copy and simulated GitHub responses."""
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import updater

IMAGE = Path(__file__).resolve().parent.parent / "dist/UN5-Netplay-x86_64.AppImage"


@unittest.skipUnless(sys.platform.startswith("linux") and IMAGE.is_file()
                     and os.environ.get("UN5_TEST_GUI_UPDATES") == "1", "Opt-in Linux GUI integration test")
class AppImageUpdateIntegrationTests(unittest.TestCase):
    def test_update_progress_atomic_replacement_and_restarted_appimage(self):
        from tkinter import ttk
        payload = IMAGE.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        name = updater.release_info.ASSET_NAMES["linux"]
        release = updater.Release("0.1.2A", "https://github.com/example/repo/releases/download/0.1.2A/" + name,
                                  "https://github.com/example/repo/releases/download/0.1.2A/" + name + ".sha256",
                                  len(payload), name)
        labels = []
        configure = ttk.Label.configure

        def capture_label(widget, *args, **kwargs):
            if "text" in kwargs:
                labels.append(kwargs["text"])
            return configure(widget, *args, **kwargs)

        class NetworkStream(io.BytesIO):
            def read(self, size=-1):
                time.sleep(0.002)
                return super().read(size)

        with tempfile.TemporaryDirectory(prefix="un5-linux-update-") as folder:
            target = Path(folder) / "Netplay prueba actualización.AppImage"
            old = bytearray(payload)
            old[15] ^= 1  # Unused ELF identification padding; keep the AppImage runnable.
            target.write_bytes(old)
            target.chmod(0o755)
            restarted = []
            output = Path(folder) / "restart.log"

            def restart_self_test(binary, stage):
                with output.open("w") as log:
                    process = subprocess.Popen([str(binary), "--self-test"], env=updater.restart_environment(stage),
                                               stdout=log, stderr=subprocess.STDOUT)
                restarted.append(process)
                return process

            responses = [io.BytesIO(f"{digest}  {name}\n".encode()), NetworkStream(payload)]
            with patch.object(updater, "current_binary", return_value=target), \
                    patch.object(updater, "find_update", return_value=release), \
                    patch.object(updater, "_response", side_effect=responses), \
                    patch.object(updater, "_configure_log"), \
                    patch.object(updater, "start_binary", side_effect=restart_self_test), \
                    patch.object(ttk.Label, "configure", capture_label):
                self.assertTrue(updater.check_for_updates_on_startup())
            self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), digest)
            self.assertTrue(any("Descargando" in label for label in labels))
            self.assertTrue(any("Reiniciando" in label for label in labels))
            self.assertEqual(restarted[0].wait(timeout=30), 0, output.read_text())
            self.assertIn("OK:", output.read_text())
            stage, = Path(folder).glob(updater.STAGE_PREFIX + "*")
            self.assertEqual((stage / "previous").read_bytes(), old)
            with patch.object(updater, "current_binary", return_value=target), \
                    patch.dict(os.environ, {"UN5_UPDATE_STAGE": str(stage)}):
                updater.confirm_startup()
            deadline = time.monotonic() + 5
            while stage.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertFalse(stage.exists())

    def test_connection_error_keeps_installed_binary_and_continues(self):
        with tempfile.TemporaryDirectory(prefix="un5-update-offline-") as folder:
            target = Path(folder) / "Netplay.AppImage"
            target.write_bytes(b"working version")
            with patch.object(updater, "current_binary", return_value=target), \
                    patch.object(updater, "find_update", side_effect=OSError("offline")), \
                    patch.object(updater, "_configure_log"), patch.object(updater.LOG, "exception"), \
                    patch.object(updater, "schedule_install") as install:
                self.assertFalse(updater.check_for_updates_on_startup())
                install.assert_not_called()
            self.assertEqual(target.read_bytes(), b"working version")


if __name__ == "__main__":
    unittest.main()
