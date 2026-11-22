import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from unittest import mock

import app as app_module
import backup
import database
import serve
from tests.helpers import ApiTestCase

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def temp_dir(test):
    path = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, path, ignore_errors=True)
    return path


class FrontendServingTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.dist = temp_dir(self)
        os.makedirs(os.path.join(self.dist, "assets"))
        with open(os.path.join(self.dist, "index.html"), "w", encoding="utf-8") as f:
            f.write("<!DOCTYPE html><title>detoate — Casa</title>")
        with open(os.path.join(self.dist, "assets", "index-abc123.js"), "w") as f:
            f.write("console.log('casa')")
        patcher = mock.patch.object(app_module, "FRONTEND_DIST", self.dist)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_index_is_served_and_never_cached(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("detoate — Casa", r.get_data(as_text=True))
        self.assertIn("no-cache", r.headers["Cache-Control"])

    def test_hashed_assets_are_cached(self):
        r = self.client.get("/assets/index-abc123.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("max-age=31536000", r.headers["Cache-Control"])
        r.close()

    def test_missing_files_and_api_routes_stay_json_404(self):
        self.assertError(self.client.get("/assets/nu-exista.js"), 404)
        self.assertError(self.client.get("/assets/../../app.py"), 404)
        self.assertError(self.client.get("/api/nu-exista"), 404, "nu există")

    def test_unbuilt_interface_explains_itself(self):
        with mock.patch.object(app_module, "FRONTEND_DIST", os.path.join(self.dist, "lipsa")):
            r = self.client.get("/")
        self.assertEqual(r.status_code, 503)
        self.assertIn("npm run build", r.get_data(as_text=True))


class BackupTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.dir = temp_dir(self)
        patcher = mock.patch.dict(os.environ, {"DETOATE_BACKUP_DIR": self.dir, "DETOATE_BACKUP_KEEP": "3"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.product("100", "Pâine")

    def product(self, code, name):
        r = self.client.post("/api/products", json={"code": code, "name": name,
                                                    "price_bani": 450})
        self.assertEqual(r.status_code, 201, r.get_json())

    def names_in(self, path):
        conn = database.sqlite3.connect(path)
        try:
            return [r[0] for r in conn.execute("SELECT name FROM products WHERE sale_type = 'unit' ORDER BY id")]
        finally:
            conn.close()

    def test_backup_is_a_verified_copy(self):
        path = backup.run()
        self.assertTrue(os.path.basename(path).startswith("detoate-") and path.endswith(".db"))
        self.assertEqual(self.names_in(path), ["Pâine"])
        self.assertIsNone(backup._check(path))
        self.assertEqual(backup.list_backups(), [path])
        backup.run()
        # nimic altceva în folder: nici .partial, nici -wal/-shm rămase de la copie
        self.assertEqual(sorted(os.listdir(self.dir)), sorted(os.path.basename(p) for p in backup.list_backups()))

    def test_only_the_newest_are_kept(self):
        for day in range(1, 6):
            open(os.path.join(self.dir, f"detoate-2026-01-0{day}_120000.db"), "w").close()
        newest = backup.run()
        self.assertEqual([os.path.basename(p) for p in backup.list_backups()],
                         [os.path.basename(newest), "detoate-2026-01-05_120000.db", "detoate-2026-01-04_120000.db"])

    def test_extra_copy_and_unavailable_extra_folder(self):
        extra = temp_dir(self)
        with mock.patch.dict(os.environ, {"DETOATE_BACKUP_COPY_DIR": extra}):
            path = backup.run()
        self.assertEqual(os.listdir(extra), [os.path.basename(path)])
        not_a_folder = os.path.join(extra, os.path.basename(path))  # un fișier, nu un folder
        with mock.patch.dict(os.environ, {"DETOATE_BACKUP_COPY_DIR": not_a_folder}), self.assertLogs("detoate.backup", "WARNING"):
            self.assertTrue(os.path.exists(backup.run()))

    def test_is_due(self):
        self.assertTrue(backup.is_due(4))
        path = backup.run()
        self.assertFalse(backup.is_due(4))
        five_hours_ago = time.time() - 5 * 3600
        os.utime(path, (five_hours_ago, five_hours_ago))
        self.assertTrue(backup.is_due(4))

    def test_restore_replaces_the_database_and_keeps_the_previous_one(self):
        saved = backup.run()
        self.product("200", "Lapte")
        with mock.patch.object(backup, "server_running", return_value=False):
            before_restore = backup.restore(saved)
        self.assertEqual(self.names_in(database.DB_PATH), ["Pâine"])
        self.assertEqual(self.names_in(before_restore), ["Pâine", "Lapte"])  # restaurarea se poate desface
        self.assertEqual(self.client.get("/api/products?q=lapte").get_json()["total"], 0)

    def test_restore_refuses_while_the_app_runs_or_with_a_bad_file(self):
        saved = backup.run()
        with mock.patch.object(backup, "server_running", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "aplicația rulează"):
                backup.restore(saved)
        junk = os.path.join(self.dir, "altceva.db")
        with open(junk, "wb") as f:
            f.write(b"nu e sqlite" * 100)
        empty = os.path.join(self.dir, "goala.db")
        database.sqlite3.connect(empty).close()
        with mock.patch.object(backup, "server_running", return_value=False):
            for path, message in ((junk, "nu e o bază de date SQLite"), (empty, "nu e o bază de date detoate")):
                with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, message):
                    backup.restore(path)
        self.assertEqual(self.names_in(database.DB_PATH), ["Pâine"])

    def test_missing_database(self):
        with mock.patch.object(database, "DB_PATH", os.path.join(self.dir, "nu-exista.db")):
            with self.assertRaises(FileNotFoundError):
                backup.run()

    def test_backup_loop_survives_errors(self):
        stop = serve.threading.Event()
        backup_calls = []

        def failing_run():
            backup_calls.append(1)
            stop.set()
            raise RuntimeError("disc plin")

        with mock.patch.object(backup, "run", failing_run), self.assertLogs("detoate", "ERROR"):
            serve.backup_loop(4, stop, check_seconds=0)
        self.assertEqual(backup_calls, [1])


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServeTest(unittest.TestCase):
    """serve.py ca proces separat, cum îl pornește detoate.exe."""

    def env(self, data):
        env = {k: v for k, v in os.environ.items() if not k.startswith("DETOATE_")}
        env.update(DETOATE_DB_PATH=os.path.join(data, "detoate.db"), DETOATE_FISCAL_SIMULATE="1")
        return env

    def test_init_only_creates_the_data_folder(self):
        data = os.path.join(temp_dir(self), "AppData", "detoate")
        p = subprocess.run([sys.executable, "serve.py", "--init-only"], cwd=BACKEND_DIR, env=self.env(data),
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(os.path.exists(os.path.join(data, "detoate.db")))
        self.assertTrue(os.path.exists(os.path.join(data, "logs", "detoate.log")))

    @unittest.skipUnless(importlib.util.find_spec("waitress"), "waitress nu e instalat (pip install -r requirements.txt)")
    def test_production_server(self):
        data, dist = temp_dir(self), temp_dir(self)
        with open(os.path.join(dist, "index.html"), "w", encoding="utf-8") as f:
            f.write("<title>detoate</title>")
        port = free_port()
        env = {**self.env(data), "DETOATE_PORT": str(port), "DETOATE_FRONTEND_DIST": dist}
        server = subprocess.Popen([sys.executable, "serve.py"], cwd=BACKEND_DIR, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.addCleanup(server.wait, 10)
        self.addCleanup(server.terminate)
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                urllib.request.urlopen(base + "/api/health", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        with urllib.request.urlopen(base + "/api/health") as r:
            self.assertEqual((r.headers["Server"], json.load(r)), ("detoate", {"status": "ok"}))
        with urllib.request.urlopen(base + "/") as r:
            self.assertIn("<title>detoate</title>", r.read().decode())
        with urllib.request.urlopen(base + "/api/fiscal/status") as r:
            self.assertEqual(json.load(r)["mode"], "simulate")
        for _ in range(50):  # copia de la pornire
            if backup.list_backups(os.path.join(data, "backups")):
                break
            time.sleep(0.1)
        self.assertEqual(len(backup.list_backups(os.path.join(data, "backups"))), 1)
        with open(os.path.join(data, "logs", "detoate.log"), encoding="utf-8") as f:
            self.assertIn("casa de marcat: simulate", f.read())


if __name__ == "__main__":
    unittest.main()
