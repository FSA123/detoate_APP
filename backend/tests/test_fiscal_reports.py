import unittest
from datetime import date, timedelta
from unittest import mock

import fiscal
import tremol
from tests.fake_tremol import FakeTremol
from tests.test_payment import PaymentTestCase


class FiscalReportsTestCase(PaymentTestCase):
    def report(self, **body):
        return self.client.post("/api/fiscal/reports", json=body)

    def created(self, **body):
        r = self.report(**body)
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()

    def sale(self, method="cash", pieces=1):
        oid = self.order((self.bread, pieces * 1000))  # 4,50 lei bucata
        r = self.pay(oid, payment_method=method)
        self.assertEqual(r.status_code, 200, r.get_json())
        return oid

    def z_of(self, order_id):
        return self.sql("SELECT fiscal_z_number FROM orders WHERE id = ?", (order_id,))[0][0]

    def totals(self, report):
        return report["total_bani"], report["cash_bani"], report["card_bani"], report["details"]["receipts"]


class SimulatedReportsTest(FiscalReportsTestCase):
    def test_x_report_shows_the_day_without_closing_it(self):
        a = self.sale("cash", pieces=2)
        self.sale("card")
        x = self.created(type="X")
        self.assertEqual((x["type"], x["z_number"], x["simulated"], x["details"]["device"]), ("X", None, True, None))
        self.assertEqual(self.totals(x), (1350, 900, 450, 2))
        self.assertIsNone(self.z_of(a))

    def test_z_report_numbers_and_tags_the_receipts_it_closes(self):
        a = self.sale()
        z1 = self.created(type="Z")
        self.assertEqual((z1["z_number"], self.totals(z1)), (1, (450, 450, 0, 1)))
        b = self.sale("card", pieces=3)
        z2 = self.created(type="Z")
        self.assertEqual((z2["z_number"], self.totals(z2)), (2, (1350, 0, 1350, 1)))
        self.assertEqual((self.z_of(a), self.z_of(b)), (1, 2))
        self.assertEqual(self.totals(self.created(type="Z")), (0, 0, 0, 0))

    def test_unreported_totals_preview_the_next_z(self):
        self.sale("cash", pieces=2)
        self.sale("card")
        self.assertEqual(self.client.get("/api/fiscal/unreported").get_json(),
                         {"receipts": 2, "total_bani": 1350, "cash_bani": 900, "card_bani": 450, "simulated": True})
        self.created(type="Z")
        self.assertEqual(self.client.get("/api/fiscal/unreported").get_json()["receipts"], 0)

    def test_unpaid_orders_are_not_counted(self):
        self.order((self.bread, 1000))
        cancelled = self.order((self.bread, 1000))
        self.client.post(f"/api/orders/{cancelled}/cancel")
        self.assertEqual(self.totals(self.created(type="Z")), (0, 0, 0, 0))
        self.assertIsNone(self.z_of(cancelled))

    def test_period_report(self):
        self.sale(pieces=2)
        today = date.today().isoformat()
        r = self.created(type="period", date_from=today, date_to=today)
        self.assertEqual((r["date_from"], r["date_to"], r["z_number"]), (today, today, None))
        self.assertEqual(self.totals(r), (900, 900, 0, 1))

    def test_validation(self):
        today = date.today()
        cases = [
            ({}, "'type' este obligatoriu"),
            ({"type": "Y"}, "unul dintre: X, Z, period"),
            ({"type": "period", "date_to": today.isoformat()}, "'date_from' este obligatoriu"),
            ({"type": "period", "date_from": "2026-13-01", "date_to": "2026-10-01"}, "dată AAAA-LL-ZZ"),
            ({"type": "period", "date_from": "2026-10-02", "date_to": "2026-10-01"}, "este după"),
            ({"type": "period", "date_from": today.isoformat(), "date_to": (today + timedelta(days=1)).isoformat()},
             "zile viitoare"),
            ({"type": "X", "date_from": "2026-10-01"}, "doar la raportul 'period'"),
        ]
        for body, message in cases:
            with self.subTest(body=body):
                self.assertError(self.report(**body), 400, message)
        self.assertEqual(self.client.get("/api/fiscal/reports").get_json()["total"], 0)

    def test_log_newest_first(self):
        self.created(type="X")
        self.created(type="Z")
        body = self.client.get("/api/fiscal/reports").get_json()
        self.assertEqual([r["type"] for r in body["items"]], ["Z", "X"])
        self.assertEqual(body["total"], 2)


class TremolReportsTest(FiscalReportsTestCase):
    def setUp(self):
        super().setUp()
        self.device = FakeTremol()
        printer = tremol.TremolPrinter(self.device, timeout=0.3)
        for p in (mock.patch.multiple(fiscal, SIMULATE=False, TREMOL_PORT="COM9"),
                  mock.patch.object(fiscal, "_tremol", return_value=printer)):
            p.start()
            self.addCleanup(p.stop)

    def test_sale_and_z_report_on_the_till(self):
        oid = self.sale(pieces=2)
        order = self.get(oid)
        self.assertEqual((order["fiscal_receipt_number"], order["fiscal_simulated"]), ("42", False))
        self.assertEqual(self.device.printed[0]["lines"][0]["name"], "Paine")
        z = self.created(type="Z")
        self.assertEqual((z["z_number"], z["simulated"], self.totals(z)), (18, False, (900, 900, 0, 1)))
        self.assertEqual(z["details"]["device"], {"total_bani": 900, "cash_bani": 900, "card_bani": 0})
        self.assertEqual((self.z_of(oid), self.device.reports), (18, ["Z"]))

    def test_real_z_leaves_simulated_receipts_alone(self):
        with mock.patch.multiple(fiscal, SIMULATE=True, TREMOL_PORT=""):
            simulated = self.sale()
        self.assertEqual(self.totals(self.created(type="Z")), (0, 0, 0, 0))
        self.assertIsNone(self.z_of(simulated))

    def test_refused_report_is_not_logged(self):
        self.device.refuse[0x7C] = "10"
        self.assertError(self.report(type="Z"), 502, "lipsă hârtie")
        self.assertEqual(self.client.get("/api/fiscal/reports").get_json()["total"], 0)

    def test_unconfigured_till(self):
        with mock.patch.object(fiscal, "TREMOL_PORT", ""):
            self.assertError(self.report(type="X"), 503, "nu este configurată")

    def test_refused_receipt_message_reaches_the_cashier_once(self):
        oid = self.order((self.bread, 1000))
        self.device.refuse[0x31] = "10"
        r = self.pay(oid, payment_method="cash")
        self.assertError(r, 502, "Casa a refuzat bonul: casa: lipsă hârtie")
        self.assertEqual(r.get_json()["error"].count("refuzat"), 1)
        self.assertEqual((self.status(oid), self.device.cancelled), ("pending", 1))

    def test_lost_connection_then_retry_does_not_print_twice(self):
        oid = self.order((self.bread, 1000))
        self.device.silent = {0x38}
        self.assertError(self.pay(oid, payment_method="cash"), 503, "Legătura cu casa de marcat")
        self.assertEqual(self.status(oid), "pending")
        r = self.pay(oid, payment_method="cash")
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual((r.get_json()["order"]["fiscal_receipt_number"], len(self.device.printed)), ("42", 1))


if __name__ == "__main__":
    unittest.main()
