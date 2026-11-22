import unittest
from datetime import date, timedelta

from routes.reports import vat_included
from tests.test_payment import PaymentTestCase


class SalesTestCase(PaymentTestCase):
    """Două bonuri plătite azi, plus unul deschis și unul anulat care nu trebuie numărate."""

    def setUp(self):
        super().setUp()
        self.milk = self.create(code="300", name="Lapte", price_bani=1210)
        self.cash_order = self.order((self.tomatoes, 1250), (self.bread, 2000))   # 11,24 + 9,00
        self.pay(self.cash_order, payment_method="cash", cash_received_bani=5000)
        self.card_order = self.order((self.milk, 1000), (self.bread, 1000))       # 12,10 + 4,50
        self.pay(self.card_order, payment_method="card")
        self.order((self.bread, 5000))
        cancelled = self.order((self.milk, 1000))
        self.client.post(f"/api/orders/{cancelled}/cancel")


class SalesReportTest(SalesTestCase):
    def report(self, **params):
        r = self.client.get("/api/reports/sales", query_string=params)
        self.assertEqual(r.status_code, 200, r.get_json())
        return r.get_json()

    def test_today(self):
        body = self.report()
        today = date.today().isoformat()
        self.assertEqual((body["date_from"], body["date_to"]), (today, today))
        self.assertEqual(body["totals"], {"receipts": 2, "total_bani": 3684, "cash_bani": 2024,
                                          "card_bani": 1660, "simulated_receipts": 2,
                                          "vat_bani": 639})  # 21% conținut în 36,84 lei
        self.assertEqual([(c["name"], c["sale_type"], c["total_bani"], c["lines"]) for c in body["by_category"]],
                         [("La bucată", "unit", 2560, 3), ("La kilogram", "weight", 1124, 1)])
        self.assertEqual(body["by_day"], [{"day": today, "receipts": 2, "total_bani": 3684}])
        self.assertEqual([(p["name"], p["sale_type"], p["quantity_milli"], p["total_bani"]) for p in body["top_products"]],
                         [("Pâine", "unit", 3000, 1350), ("Lapte", "unit", 1000, 1210), ("Roșii", "weight", 1250, 1124)])

    def test_other_period_is_empty(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        body = self.report(date_from=yesterday, date_to=yesterday)
        self.assertEqual((body["totals"]["receipts"], body["totals"]["total_bani"]), (0, 0))
        self.assertEqual(body["totals"]["vat_bani"], 0)
        self.assertEqual((body["by_category"], body["by_day"], body["top_products"]), ([], [], []))
        self.assertNotIn("by_vat", body)

    def test_vat_follows_the_rate_saved_on_each_line(self):
        # un bon emis cândva cu altă cotă își păstrează TVA-ul
        self.sql("UPDATE order_items SET vat_percent = 11 WHERE product_id = ?", (self.tomatoes["id"],))
        self.assertEqual(self.report()["totals"]["vat_bani"], vat_included(1124, 11) + vat_included(2560, 21))

    def test_range_includes_both_ends(self):
        today = date.today()
        body = self.report(date_from=(today - timedelta(days=7)).isoformat(), date_to=today.isoformat())
        self.assertEqual(body["totals"]["receipts"], 2)

    def test_validation(self):
        self.assertError(self.client.get("/api/reports/sales?date_from=19.10.2026"), 400, "AAAA-LL-ZZ")
        self.assertError(self.client.get("/api/reports/sales?date_from=2026-10-02&date_to=2026-10-01"), 400, "este după")

    def test_vat_included(self):
        self.assertEqual([vat_included(12100, 21.0), vat_included(11100, 11.0), vat_included(2474, 11.0),
                          vat_included(500, 0.0)], [2100, 1100, 245, 0])


if __name__ == "__main__":
    unittest.main()
