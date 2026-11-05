import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import appimage_start as start


class AppImageStartupTests(unittest.TestCase):
    def setUp(self):
        updater = patch.object(start, "check_for_updates_on_startup", return_value=False)
        updater.start()
        self.addCleanup(updater.stop)

    def test_update_restart_does_not_open_pcsx2_or_old_launcher(self):
        with patch.object(start.sys, "argv", ["AppRun"]), \
                patch.object(start, "check_for_updates_on_startup", return_value=True), \
                patch.object(start, "check_flatpak") as preflight, \
                patch.object(start.subprocess, "Popen") as spawn:
            self.assertEqual(start.main(), 0)
            preflight.assert_not_called()
            spawn.assert_not_called()

    def test_missing_flatpak_explains_requirement(self):
        with patch.object(start.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "No se encontró Flatpak"):
                start.check_flatpak()

    def test_missing_pcsx2_gives_install_command(self):
        with patch.object(start.shutil, "which", return_value="/usr/bin/flatpak"), \
                patch.object(start.subprocess, "run", return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(RuntimeError, "flatpak install flathub net.pcsx2.PCSX2"):
                start.check_flatpak()

    def test_failed_preflight_starts_neither_application(self):
        with patch.object(start.sys, "argv", ["AppRun"]), \
                patch.object(start, "check_flatpak", side_effect=RuntimeError("missing")), \
                patch.object(start, "show_error") as error, \
                patch.object(start.subprocess, "Popen") as spawn:
            self.assertEqual(start.main(), 1)
            spawn.assert_not_called()
            error.assert_called_once_with("missing")

    def test_starts_original_script_and_keeps_stop_file_writable(self):
        process = Mock()
        process.wait.side_effect = start.subprocess.TimeoutExpired("flatpak", 0.8)
        temporary_dirs = []

        def launcher_loop():
            # The actual backend uses TEMP for the STOP signal, even from a read-only AppImage.
            from launcher_core import Backend
            backend = Backend()
            backend.stop_file.write_text("stop")
            self.assertEqual(backend.stop_file.read_text(), "stop")
            temporary_dirs.append(backend.stop_file.parent)

        launcher = Mock()
        launcher.mainloop.side_effect = launcher_loop
        with tempfile.TemporaryDirectory() as data, \
                patch.dict(os.environ, {"XDG_STATE_HOME": data, "DISPLAY": ":0"}), \
                patch.object(start.sys, "argv", ["AppRun"]), \
                patch.object(start, "check_flatpak"), \
                patch.dict("sys.modules", {"launcher": SimpleNamespace(Launcher=Mock(return_value=launcher))}), \
                patch.object(start.subprocess, "Popen", return_value=process) as spawn:
            self.assertEqual(start.main(), 0)
            self.assertEqual(spawn.call_args.args[0], ["bash", str(start.PROJECT / "2 - PCSX2 Flatpak.sh")])
            launcher.mainloop.assert_called_once()
            process.terminate.assert_not_called()
            self.assertTrue((Path(data) / "un5-netplay/pcsx2.log").is_file())
        self.assertFalse(temporary_dirs[0].exists())

    def test_failed_pcsx2_does_not_start_launcher(self):
        with tempfile.TemporaryDirectory() as data, \
                patch.dict(os.environ, {"XDG_STATE_HOME": data, "DISPLAY": ":0"}), \
                patch.object(start.sys, "argv", ["AppRun"]), \
                patch.object(start, "check_flatpak"), \
                patch.object(start, "show_error") as error, \
                patch.object(start.subprocess, "Popen") as spawn:
            spawn.return_value.wait.return_value = 1
            self.assertEqual(start.main(), 1)
            self.assertIn("No se pudo abrir PCSX2", error.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
