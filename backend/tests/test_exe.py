import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

import backup
import detoate_exe


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.path = os.path.join(self.dir, "config.txt")

    def write(self, text, encoding="utf-8"):
        with open(self.path, "w", encoding=encoding) as f:
            f.write(text)

    def test_first_start_creates_the_template_and_it_loads_cleanly(self):
        env = {}
        self.assertEqual(detoate_exe.load_config(self.path, env), [])
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), detoate_exe.CONFIG_TEMPLATE)
        self.assertEqual((env["DETOATE_TREMOL_PORT"], env["DETOATE_PORT"], env["DETOATE_FISCAL_SIMULATE"]),
                         ("", "5000", ""))

    def test_values_typos_and_notepad_bom(self):
        self.write("# comentariu\n\nDETOATE_TREMOL_PORT = COM3 \nDETOATE_TREMOL_PROT=COM4\nport COM5\n",
                   encoding="utf-8-sig")
        env = {}
        warnings = detoate_exe.load_config(self.path, env)
        self.assertEqual(env, {"DETOATE_TREMOL_PORT": "COM3"})
        self.assertEqual(warnings, [
            "config.txt, rândul 4: „DETOATE_TREMOL_PROT=COM4” nu e o setare cunoscută — ignorat",
            "config.txt, rândul 5: „port COM5” nu e o setare cunoscută — ignorat",
        ])

    def test_environment_wins_over_the_file(self):
        self.write("DETOATE_FISCAL_SIMULATE=\n")
        env = {"DETOATE_FISCAL_SIMULATE": "1"}
        detoate_exe.load_config(self.path, env)
        self.assertEqual(env["DETOATE_FISCAL_SIMULATE"], "1")

    def test_data_lives_outside_the_app_folder(self):
        env = {"LOCALAPPDATA": r"C:\Users\casa\AppData\Local", "DETOATE_DATA_DIR": ""}
        detoate_exe.apply_defaults(env, frozen_dir="/tmp/_MEI123")
        data = os.path.join(r"C:\Users\casa\AppData\Local", "detoate")
        self.assertEqual((env["DETOATE_DATA_DIR"], env["DETOATE_DB_PATH"], env["DETOATE_BACKUP_DIR"]),
                         (data, os.path.join(data, "detoate.db"), os.path.join(data, "backups")))
        self.assertEqual(env["DETOATE_FRONTEND_DIST"], os.path.join("/tmp/_MEI123", "frontend_dist"))

    def test_explicit_paths_are_kept(self):
        env = {"DETOATE_DATA_DIR": "/date", "DETOATE_DB_PATH": "/alta/baza.db"}
        detoate_exe.apply_defaults(env)
        self.assertEqual((env["DETOATE_DB_PATH"], env["DETOATE_LOG_DIR"]), ("/alta/baza.db", os.path.join("/date", "logs")))
        self.assertNotIn("DETOATE_FRONTEND_DIST", env)  # rulat cu Python: interfața din frontend/dist


class AutostartTest(unittest.TestCase):
    def test_follows_the_exe_and_can_be_turned_off(self):
        startup = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, startup)
        path = detoate_exe.sync_autostart(True, r"C:\detoate\detoate.exe", startup)
        with open(path, newline="") as f:
            self.assertEqual(f.read(), '@echo off\r\nstart "detoate" /min "C:\\detoate\\detoate.exe"\r\n')
        detoate_exe.sync_autostart(True, r"D:\casa\detoate.exe", startup)  # mutat în alt folder
        with open(path, newline="") as f:
            self.assertIn(r'"D:\casa\detoate.exe"', f.read())
        self.assertIsNone(detoate_exe.sync_autostart(False, r"D:\casa\detoate.exe", startup))
        self.assertFalse(os.path.exists(path))


class CommandsTest(unittest.TestCase):
    def run_command(self, argv, answer="DA"):
        out = io.StringIO()
        with mock.patch.object(backup, "main", return_value=0) as backup_main, \
                mock.patch("builtins.input", return_value=answer), redirect_stdout(out):
            code = detoate_exe._command(argv)
        return code, backup_main, out.getvalue()

    def test_backup_and_restore_commands(self):
        self.assertEqual(self.run_command(["backup", "--list"])[1].call_args.args, (["--list"],))
        self.assertEqual(self.run_command(["restore", "copie.db"])[1].call_args.args, (["--restore", "copie.db"],))
        self.assertEqual(self.run_command(["restore"])[1].call_args.args, (["--list"],))

    def test_copy_dropped_on_the_exe_needs_confirmation(self):
        fd, copy = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(os.remove, copy)
        code, backup_main, _ = self.run_command([copy], answer="da")
        self.assertEqual((code, backup_main.called), (1, False))
        code, backup_main, _ = self.run_command([copy], answer="DA")
        self.assertEqual(backup_main.call_args.args, (["--restore", copy],))

    def test_unknown_command_shows_the_help(self):
        code, backup_main, out = self.run_command(["porneste"])
        self.assertEqual((code, backup_main.called), (2, False))
        self.assertIn("detoate.exe check-till", out)


if __name__ == "__main__":
    unittest.main()
