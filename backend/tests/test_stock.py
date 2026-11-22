import unittest

from tests.test_products import ProductsTestCase


class StockMovementsTest(ProductsTestCase):
    def move(self, product_id, /, **body):
        return self.client.post(f"/api/products/{product_id}/stock", json=body)

    def stock(self, product_id):
        return self.client.get(f"/api/products/{product_id}").get_json()["stock_qty"]

    def test_receipt_and_adjustment_update_stock(self):
        p = self.create()
        r = self.move(p["id"], delta_qty=10, reason="receipt", note="Factura 123")
        self.assertEqual(r.status_code, 201, r.get_json())
        m = r.get_json()["movement"]
        self.assertEqual(
            (m["product_id"], m["delta_qty"], m["reason"], m["note"], m["order_id"]),
            (p["id"], 10, "receipt", "Factura 123", None),
        )
        self.assertEqual(r.get_json()["product"]["stock_qty"], 10)
        r = self.move(p["id"], delta_qty=-3, reason="adjustment", note="Sac deschis")
        self.assertEqual(r.get_json()["product"]["stock_qty"], 7)

    def test_stock_can_go_negative(self):
        p = self.create()
        r = self.move(p["id"], delta_qty=-2, reason="adjustment")
        self.assertEqual(r.get_json()["product"]["stock_qty"], -2)
        self.assertEqual(r.get_json()["movement"]["note"], "")

    def test_low_stock_flag_follows_movements(self):
        p = self.create(min_stock_qty=3, initial_stock_qty=5)
        self.assertIs(p["low_stock"], False)
        r = self.move(p["id"], delta_qty=-2, reason="adjustment")
        self.assertIs(r.get_json()["product"]["low_stock"], True)

    def test_validation(self):
        p = self.create()
        cases = [
            ({"reason": "receipt"}, "'delta_qty' este obligatoriu"),
            ({"delta_qty": 5}, "'reason' este obligatoriu"),
            ({"delta_qty": 0, "reason": "adjustment"}, "nu poate fi 0"),
            ({"delta_qty": 1.5, "reason": "adjustment"}, "număr întreg"),
            ({"delta_qty": -5, "reason": "receipt"}, "trebuie să fie pozitivă"),
            ({"delta_qty": 5, "reason": "sale"}, "unul dintre: receipt, adjustment"),
            ({"delta_qty": 2_000_000, "reason": "receipt"}, "cel mult 1000000"),
            ({"delta_qty": 5, "reason": "receipt", "note": "x" * 501}, "cel mult 500"),
            ({"delta_qty": 5, "reason": "receipt", "product_id": 2}, "Câmpuri necunoscute: product_id"),
        ]
        for body, message in cases:
            with self.subTest(body=body):
                self.assertError(self.move(p["id"], **body), 400, message)
        self.assertEqual(self.stock(p["id"]), 0)  # nicio cerere invalidă nu a atins stocul

    def test_missing_product(self):
        self.assertError(self.move(999, delta_qty=1, reason="receipt"), 404)
        self.assertError(self.client.get("/api/products/999/movements"), 404)

    def test_inactive_product_accepts_movements(self):
        p = self.create(active=False)
        self.assertEqual(self.move(p["id"], delta_qty=4, reason="receipt").status_code, 201)

    def test_history_newest_first_with_pagination(self):
        p = self.create(initial_stock_qty=5)
        self.move(p["id"], delta_qty=10, reason="receipt")
        self.move(p["id"], delta_qty=-1, reason="adjustment")
        body = self.client.get(f"/api/products/{p['id']}/movements").get_json()
        self.assertEqual(body["total"], 3)
        self.assertEqual([m["delta_qty"] for m in body["items"]], [-1, 10, 5])
        page = self.client.get(f"/api/products/{p['id']}/movements?limit=1&offset=1").get_json()
        self.assertEqual([m["delta_qty"] for m in page["items"]], [10])

    def test_stock_always_equals_sum_of_movements(self):
        p = self.create(initial_stock_qty=7)
        for delta, reason in [(3, "receipt"), (-4, "adjustment"), (12, "receipt"), (-1, "adjustment")]:
            self.move(p["id"], delta_qty=delta, reason=reason)
        total = self.sql("SELECT SUM(delta_qty) FROM stock_movements WHERE product_id = ?", (p["id"],))[0][0]
        self.assertEqual((self.stock(p["id"]), total), (17, 17))


if __name__ == "__main__":
    unittest.main()
