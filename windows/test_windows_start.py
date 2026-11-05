from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import windows_start as start
import updater


class WindowsEntryPointTests(unittest.TestCase):
    def setUp(self):
        updating = patch.object(updater, "check_for_updates_on_startup", return_value=False)
        updating.start()
        self.addCleanup(updating.stop)

    def test_update_restart_does_not_open_old_gui(self):
        with patch.object(updater, "check_for_updates_on_startup", return_value=True), \
                patch.object(start, "run_gui") as gui:
            self.assertEqual(start.main([]), 0)
            gui.assert_not_called()

    def test_worker_does_not_check_for_updates(self):
        with patch.object(updater, "check_for_updates_on_startup") as check, \
                patch.object(start, "run_worker", return_value=0):
            self.assertEqual(start.main(["-u", str(start.project_dir() / "netplay.py"), "--help"]), 0)
            check.assert_not_called()

    def test_normal_start_opens_only_launcher(self):
        with patch.object(start, "run_gui", return_value=0) as gui, \
                patch.object(start, "run_worker") as worker, \
                patch.object(start.subprocess, "Popen") as spawn:
            self.assertEqual(start.main([]), 0)
            gui.assert_called_once_with()
            worker.assert_not_called()
            spawn.assert_not_called()

    def test_accepts_existing_backend_and_koth_commands(self):
        for name in ("netplay.py", "pine.py"):
            with self.subTest(name=name):
                path = start.project_dir() / name
                script, args = start.worker_script(["-u", str(path), "--pine-slot", "28011"])
                self.assertEqual(script, path)
                self.assertEqual(args, ["--pine-slot", "28011"])

    def test_rejects_external_or_unexpected_scripts(self):
        with tempfile.TemporaryDirectory() as folder:
            for command in ([str(Path(folder) / "netplay.py")], ["other.py"], ["-c", "print('no')"]):
                with self.subTest(command=command), self.assertRaises(ValueError):
                    start.worker_script(command)

    def test_worker_dispatch_runs_script_without_reopening_gui(self):
        script = start.project_dir() / "netplay.py"
        with patch.object(start.runpy, "run_path") as run, \
                patch.object(start.sys, "argv", ["UN5-Netplay.exe"]), \
                patch.object(start, "run_gui") as gui:
            self.assertEqual(start.main(["-u", str(script), "--help"]), 0)
            run.assert_called_once_with(str(script), run_name="__main__")
            gui.assert_not_called()


if __name__ == "__main__":
    unittest.main()
