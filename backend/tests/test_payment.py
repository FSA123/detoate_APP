import threading
import time
import unittest
from unittest import mock

import fiscal
from app import app
from tests.test_orders import VALID_CUI, OrdersTestCase


class PaymentTestCase(OrdersTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(fiscal, "SIMULATE", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def pay(self, order_id, /, **body):
        return self.client.post(f"/api/orders/{order_id}/pay", json=body)


class PayOrderTest(PaymentTestCase):
    def test_cash_payment(self):
        oid = self.order((self.tomatoes, 1250), (self.bread, 2000))  # 11,24 + 9,00
        r = self.pay(oid, payment_method="cash", cash_received_bani=5000)
        self.assertEqual(r.status_code, 200, r.get_json())
        body = r.get_json()
        o = body["order"]
        self.assertEqual(
            (o["status"], o["payment_method"], o["total_bani"], o["cash_received_bani"], body["change_bani"]),
            ("paid", "cash", 2024, 5000, 2976),
        )
        self.assertEqual((o["fiscal_receipt_number"], o["fiscal_simulated"]), (f"SIM-{oid}", True))
        self.assertIsNotNone(o["fiscalized_at"])
        self.assertEqual([i["product_name"] for i in o["items"]], ["Roșii", "Pâine"])
        self.assertIn("SIMULARE", body["fiscal_message"])

    def test_cash_defaults_to_exact_sum(self):
        body = self.pay(self.order((self.bread, 1000)), payment_method="cash").get_json()
        self.assertEqual((body["order"]["cash_received_bani"], body["change_bani"]), (450, 0))

    def test_card_payment(self):
        body = self.pay(self.order((self.bread, 1000)), payment_method="card").get_json()
        o = body["order"]
        self.assertEqual((o["status"], o["payment_method"], o["cash_received_bani"], body["change_bani"]),
                         ("paid", "card", None, None))

    def test_receipt_sent_to_fiscal_adapter(self):
        oid = self.order((self.tomatoes, 1250), (self.bread, 2000))
        with mock.patch.object(fiscal, "send_receipt", wraps=fiscal.send_receipt) as send:
            self.pay(oid, payment_method="cash", cash_received_bani=5000)
        self.assertEqual(send.call_args.args[0], fiscal.Receipt(
            order_id=oid,
            lines=(fiscal.SaleLine("Roșii", "A", 899, 1250, 1124, "kg"), fiscal.SaleLine("Pâine", "A", 450, 2000, 900, "buc")),
            total_bani=2024,
            payment_method="cash",
            cash_received_bani=5000,
            buyer_cui="",
            buyer_name="",
        ))

    def test_discounted_line_reaches_the_till_at_the_discounted_price(self):
        oid = self.order((self.bread, 2000))
        line = self.get(oid)["items"][0]["id"]
        self.client.patch(f"/api/orders/{oid}/items/{line}", json={"discount_bp": 1000})  # 4,50 − 10% = 4,05
        with mock.patch.object(fiscal, "send_receipt", wraps=fiscal.send_receipt) as send:
            self.pay(oid, payment_method="card")
        receipt = send.call_args.args[0]
        self.assertEqual((receipt.lines, receipt.total_bani), ((fiscal.SaleLine("Pâine", "A", 405, 2000, 810, "buc"),), 810))

    def test_line_with_a_new_price_reaches_the_till_at_that_price(self):
        oid = self.order((self.bread, 2000))
        line = self.get(oid)["items"][0]["id"]
        self.client.patch(f"/api/orders/{oid}/items/{line}", json={"manual_price_bani": 399})
        with mock.patch.object(fiscal, "send_receipt", wraps=fiscal.send_receipt) as send:
            self.pay(oid, payment_method="card")
        receipt = send.call_args.args[0]
        self.assertEqual((receipt.lines, receipt.total_bani), ((fiscal.SaleLine("Pâine", "A", 399, 2000, 798, "buc"),), 798))

    def test_new_price_with_a_discount_reaches_the_till_as_the_final_price(self):
        # 120 lei → preț nou 100 → 30%: casa primește doar prețul final, 70 lei (varianta A)
        product_a = self.create(code="500", name="Produs A", price_bani=12000)
        oid = self.order((product_a, 1000))
        line = self.get(oid)["items"][0]["id"]
        self.client.patch(f"/api/orders/{oid}/items/{line}", json={"manual_price_bani": 10000})
        self.client.patch(f"/api/orders/{oid}/items/{line}", json={"discount_bp": 3000})
        with mock.patch.object(fiscal, "send_receipt", wraps=fiscal.send_receipt) as send:
            r = self.pay(oid, payment_method="cash", cash_received_bani=10000)
        self.assertEqual(r.status_code, 200, r.get_json())
        receipt = send.call_args.args[0]
        self.assertEqual((receipt.lines, receipt.total_bani),
                         ((fiscal.SaleLine("Produs A", "A", 7000, 1000, 7000, "buc"),), 7000))
        self.assertEqual(r.get_json()["change_bani"], 3000)
        stored = self.get(oid)["items"][0]
        self.assertEqual((stored["list_price_bani"], stored["manual_price_bani"], stored["discount_bp"],
                          stored["unit_price_bani"]), (12000, 10000, 3000, 7000))
        r = self.client.patch(f"/api/orders/{oid}/items/{line}", json={"discount_bp": 0})  # după plată, nu se mai schimbă
        self.assertEqual(r.status_code, 409)

    def test_unit_sales_reduce_stock_weight_sales_do_not(self):
        oid = self.order((self.bread, 2000), (self.tomatoes, 500), (self.bread, 3000))
        self.pay(oid, payment_method="card")
        self.assertEqual((self.stock(self.bread), self.stock(self.tomatoes)), (5, 0))
        rows = self.sql("SELECT product_id, delta_qty, order_id FROM stock_movements WHERE reason = 'sale'")
        self.assertEqual([tuple(r) for r in rows], [(self.bread["id"], -5, oid)])

    def test_saved_customer_is_copied_again_at_payment(self):
        self.sql("INSERT INTO customers (type, name, cui) VALUES ('pj', 'SC Legume SRL', ?)", (VALID_CUI,))
        oid = self.order((self.bread, 1000), customer_id=1)
        # firma își schimbă numele cât timp bonul e deschis — pe bon intră datele de la plată
        self.sql("UPDATE customers SET name = 'SC Legume Noi SRL' WHERE id = 1")
        with mock.patch.object(fiscal, "send_receipt", wraps=fiscal.send_receipt) as send:
            o = self.pay(oid, payment_method="card").get_json()["order"]
        self.assertEqual((o["buyer_type"], o["buyer_name"], o["buyer_cui"]), ("pj", "SC Legume Noi SRL", VALID_CUI))
        self.assertEqual(send.call_args.args[0].buyer_cui, VALID_CUI)

    def test_company_buyer_typed_on_order(self):
        oid = self.order((self.bread, 1000), buyer_type="pj", buyer_name="SC Pâine SRL", buyer_cui="RO14399840")
        with mock.patch.object(fiscal, "send_receipt", wraps=fiscal.send_receipt) as send:
            o = self.pay(oid, payment_method="card").get_json()["order"]
        self.assertEqual((o["buyer_type"], o["buyer_cui"]), ("pj", "RO14399840"))
        self.assertEqual(send.call_args.args[0].buyer_cui, "RO14399840")


class PayFailureTest(PaymentTestCase):
    def test_refused_receipt_leaves_order_pending(self):
        oid = self.order((self.bread, 1000))
        refused = fiscal.FiscalResult(ok=False, doc_number=None, receipt_number=None, message="Lipsă hârtie", raw="")
        with mock.patch.object(fiscal, "send_receipt", return_value=refused):
            self.assertError(self.pay(oid, payment_method="cash"), 502, "Lipsă hârtie")
        self.assertEqual((self.status(oid), self.stock(self.bread)), ("pending", 10))
        # după remedierea casei, plata se reîncearcă
        self.assertEqual(self.pay(oid, payment_method="cash").status_code, 200)

    def test_without_simulation_payment_fails_clearly(self):
        oid = self.order((self.bread, 1000))
        with mock.patch.object(fiscal, "SIMULATE", False):
            self.assertError(self.pay(oid, payment_method="cash"), 503, "DETOATE_FISCAL_SIMULATE=1")
        self.assertEqual(self.status(oid), "pending")

    def test_cannot_pay_twice(self):
        oid = self.order((self.bread, 1000))
        self.pay(oid, payment_method="cash")
        with mock.patch.object(fiscal, "send_receipt") as send:
            self.assertError(self.pay(oid, payment_method="card"), 409, "deja plătită")
        send.assert_not_called()
        self.assertEqual(self.stock(self.bread), 9)

    def test_concurrent_payments_print_one_receipt(self):
        # dublu-click pe „Plătește”: a doua cerere sosește cât timp casa tipărește
        oid = self.order((self.bread, 1000))
        real_send = fiscal.send_receipt

        def slow_send(receipt):
            time.sleep(0.2)
            return real_send(receipt)

        statuses = []

        def pay():
            r = app.test_client().post(f"/api/orders/{oid}/pay", json={"payment_method": "cash"})
            statuses.append(r.status_code)

        with mock.patch.object(fiscal, "send_receipt", side_effect=slow_send) as send:
            threads = [threading.Thread(target=pay) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(sorted(statuses), [200, 409])
        self.assertEqual(send.call_count, 1)
        self.assertEqual(self.stock(self.bread), 9)

    def test_cart_change_during_payment_waits_for_it(self):
        # o linie adăugată cât timp casa tipărește nu ajunge în comanda plătită fără să fie pe bon
        oid = self.order((self.bread, 1000))
        real_send = fiscal.send_receipt
        printing = threading.Event()

        def slow_send(receipt):
            printing.set()
            time.sleep(0.2)
            return real_send(receipt)

        statuses = {}

        def pay():
            r = app.test_client().post(f"/api/orders/{oid}/pay", json={"payment_method": "cash"})
            statuses["pay"] = r.status_code

        with mock.patch.object(fiscal, "send_receipt", side_effect=slow_send):
            t = threading.Thread(target=pay)
            t.start()
            self.assertTrue(printing.wait(5))
            r = self.add(oid, product_id=self.bread["id"])
            t.join()
        self.assertEqual((statuses["pay"], r.status_code), (200, 409))
        o = self.get(oid)
        self.assertEqual((o["items"][0]["quantity_milli"], o["total_bani"], self.stock(self.bread)), (1000, 450, 9))

    def test_cancelled_order(self):
        oid = self.order((self.bread, 1000))
        self.client.post(f"/api/orders/{oid}/cancel")
        self.assertError(self.pay(oid, payment_method="cash"), 409, "anulată")

    def test_empty_order(self):
        self.assertError(self.pay(self.order(), payment_method="cash"), 400, "nu are produse")

    def test_missing_order(self):
        self.assertError(self.pay(999, payment_method="cash"), 404)

    def test_validation(self):
        oid = self.order((self.bread, 1000))  # 4,50 lei
        cases = [
            ({}, "'payment_method' este obligatoriu"),
            ({"payment_method": "tichet"}, "unul dintre: cash, card"),
            ({"payment_method": "card", "cash_received_bani": 500}, "doar la plata cash"),
            ({"payment_method": "cash", "cash_received_bani": 449}, "mai mică decât totalul"),
            ({"payment_method": "cash", "cash_received_bani": 4.5}, "număr întreg"),
            ({"payment_method": "cash", "cash_received_bani": -1}, "cel puțin 0"),
            ({"payment_method": "cash", "total_bani": 1}, "Câmpuri necunoscute: total_bani"),
        ]
        with mock.patch.object(fiscal, "send_receipt") as send:
            for body, message in cases:
                with self.subTest(body=body):
                    self.assertError(self.pay(oid, **body), 400, message)
        send.assert_not_called()
        self.assertEqual(self.status(oid), "pending")


if __name__ == "__main__":
    unittest.main()
