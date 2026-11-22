import os
import sqlite3
import tempfile
import unittest

import database


class SchemaTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        database.init_db(self.path)
        # autocommit — altfel INSERT-ul din setUp ține tranzacția deschisă și
        # al doilea init_db() așteaptă 30s după lock
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.pid = self.conn.execute(
            "INSERT INTO products (code, name, sale_type, price_bani) VALUES ('101', 'Mere', 'unit', 899)"
        ).lastrowid

    def tearDown(self):
        self.conn.close()
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(self.path + suffix):
                os.remove(self.path + suffix)

    def test_init_is_idempotent(self):
        database.init_db(self.path)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0], 2)  # KG + 101

    def test_older_database_gets_the_discount_column(self):
        # o bază de dinainte de reduceri (fără coloana discount_bp), cu o linie vândută
        self.conn.execute("INSERT INTO orders DEFAULT VALUES")
        self.conn.execute(
            "INSERT INTO order_items (order_id, product_id, product_name, sale_type, quantity_milli, "
            "list_price_bani, unit_price_bani, vat_fiscal_code, vat_percent, line_total_bani) "
            "VALUES (1, ?, 'Mere', 'unit', 1000, 899, 899, 'A', 21, 899)", (self.pid,))
        self.conn.execute("ALTER TABLE order_items DROP COLUMN discount_bp")
        database.init_db(self.path)
        self.assertEqual(self.conn.execute("SELECT discount_bp, line_total_bani FROM order_items").fetchall(), [(0, 899)])

    def old_lines(self):
        """Linii ca în bazele de dinainte de prețul nou: (list, unit, reducere)."""
        self.conn.execute("INSERT INTO orders DEFAULT VALUES")
        for list_price, unit_price, discount in ((899, 899, 0),      # la prețul din catalog
                                                 (899, 800, 0),      # preț tastat de mână
                                                 (899, 809, 1000),   # reducere 10%
                                                 (899, 0, 0)):       # preț 0 tastat (versiune veche)
            self.conn.execute(
                "INSERT INTO order_items (order_id, product_id, product_name, sale_type, quantity_milli, "
                "list_price_bani, unit_price_bani, discount_bp, vat_fiscal_code, vat_percent, line_total_bani) "
                "VALUES (1, ?, 'Mere', 'unit', 1000, ?, ?, ?, 'A', 21, ?)",
                (self.pid, list_price, unit_price, discount, unit_price))

    def manual_prices(self):
        return [r[0] for r in self.conn.execute("SELECT manual_price_bani FROM order_items ORDER BY id")]

    def test_older_database_gets_the_manual_price_column(self):
        self.old_lines()
        self.conn.execute("ALTER TABLE order_items DROP COLUMN manual_price_bani")
        database.init_db(self.path)
        # doar linia cu preț tastat își păstrează prețul ca „preț nou”; prețurile încasate nu se schimbă
        self.assertEqual(self.manual_prices(), [None, 800, None, None])
        self.assertEqual([r[0] for r in self.conn.execute("SELECT unit_price_bani FROM order_items ORDER BY id")],
                         [899, 800, 809, 0])
        database.init_db(self.path)  # a doua pornire nu mai schimbă nimic
        self.assertEqual(self.manual_prices(), [None, 800, None, None])

    def test_database_from_before_discounts_gets_both_columns(self):
        self.old_lines()
        self.conn.execute("DELETE FROM order_items WHERE discount_bp <> 0")
        self.conn.execute("ALTER TABLE order_items DROP COLUMN manual_price_bani")
        self.conn.execute("ALTER TABLE order_items DROP COLUMN discount_bp")
        database.init_db(self.path)
        self.assertEqual(self.manual_prices(), [None, 800, None])
        self.assertEqual([r[0] for r in self.conn.execute("SELECT discount_bp FROM order_items")], [0, 0, 0])

    def test_manual_price_must_be_positive(self):
        self.old_lines()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE order_items SET manual_price_bani = 0 WHERE id = 1")

    def test_kg_sale_row_is_created_once_without_a_price(self):
        database.init_db(self.path)
        rows = self.conn.execute("SELECT name, sale_type, price_bani, active FROM products WHERE code = 'KG'").fetchall()
        self.assertEqual(rows, [("Marfă la kilogram", "weight", 0, 1)])

    def test_old_database_is_refused_clearly(self):
        # bază din versiunea cu cote TVA pe produs: oprire la pornire, cu mesaj
        fd, old = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(os.remove, old)
        conn = sqlite3.connect(old)
        conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, vat_rate_id INTEGER NOT NULL)")
        conn.close()
        with self.assertRaisesRegex(RuntimeError, "versiune mai veche"):
            database.init_db(old)

    def test_stock_follows_movements(self):
        # 5 lăzi recepționate, 2 deschise și scoase din stoc
        self.conn.execute("INSERT INTO stock_movements (product_id, delta_qty, reason) VALUES (?, 5, 'receipt')", (self.pid,))
        self.conn.execute("INSERT INTO stock_movements (product_id, delta_qty, reason) VALUES (?, -2, 'adjustment')", (self.pid,))
        stock = self.conn.execute("SELECT stock_qty FROM products WHERE id = ?", (self.pid,)).fetchone()[0]
        self.assertEqual(stock, 3)

    def test_price_override_flag(self):
        self.conn.execute("INSERT INTO orders DEFAULT VALUES")
        self.conn.execute(
            "INSERT INTO order_items (order_id, product_id, product_name, sale_type, quantity_milli, "
            "list_price_bani, unit_price_bani, vat_fiscal_code, vat_percent, line_total_bani) "
            "VALUES (1, ?, 'Mere', 'unit', 1000, 899, 800, 'A', 21, 800)", (self.pid,)
        )
        flag = self.conn.execute("SELECT price_overridden FROM order_items").fetchone()[0]
        self.assertEqual(flag, 1)

    def test_unit_products_need_whole_quantities(self):
        bread = self.conn.execute(
            "INSERT INTO products (code, name, sale_type, price_bani) VALUES ('200', 'Pâine', 'unit', 450)"
        ).lastrowid
        self.conn.execute("INSERT INTO orders DEFAULT VALUES")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO order_items (order_id, product_id, product_name, sale_type, quantity_milli, "
                "list_price_bani, unit_price_bani, vat_fiscal_code, vat_percent, line_total_bani) "
                "VALUES (1, ?, 'Pâine', 'unit', 1500, 450, 450, 'A', 21, 675)", (bread,)
            )

    def test_company_buyer_requires_cui(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO orders (buyer_type) VALUES ('pj')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO customers (type, name) VALUES ('pj', 'SC Test SRL')")

    def test_paid_order_requires_payment_method(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("INSERT INTO orders (status) VALUES ('paid')")

    def test_product_with_history_cannot_be_deleted(self):
        self.conn.execute("INSERT INTO stock_movements (product_id, delta_qty, reason) VALUES (1, 5, 'receipt')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM products WHERE id = 1")


if __name__ == "__main__":
    unittest.main()
