import os
import tempfile
import unittest

import database
from app import app


class ApiTestCase(unittest.TestCase):
    """Fiecare test primește o bază de date nouă, într-un fișier temporar."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self._old_db_path = database.DB_PATH
        database.DB_PATH = self.db_path
        database.init_db(self.db_path)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self):
        database.DB_PATH = self._old_db_path
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(self.db_path + suffix):
                os.remove(self.db_path + suffix)

    def assertError(self, response, status, fragment=""):
        """Răspuns de eroare cu statusul dat și mesajul conținând `fragment`."""
        self.assertEqual(response.status_code, status, response.get_json())
        self.assertIn(fragment, response.get_json()["error"])
