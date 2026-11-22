import unittest

from routes.orders import discounted_price, line_total_bani
from tests.test_products import ProductsTestCase

VALID_CUI = "RO14080700"


class OrdersTestCase(ProductsTestCase):
    def setUp(self):
        super().setUp()
        self.tomatoes = self.kg(899, "Roșii")  # vânzarea la kilogram, 8,99 lei / kg
        self.bread = self.create(code="200", name="Pâine", price_bani=450, initial_stock_qty=10)

    def new_order(self, **fields):
        r = self.client.post("/api/orders", json=fields)
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()

    def add(self, order_id, /, **body):
        return self.client.post(f"/api/orders/{order_id}/items", json=body)

    def added(self, order_id, /, **body):
        r = self.add(order_id, **body)
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()

    def order(self, *lines, **fields):
        """Comandă pending, prin API. lines: (produs, quantity_milli)."""
        oid = self.new_order(**fields)["id"]
        for product, qty in lines:
            self.added(oid, product_id=product["id"], quantity_milli=qty)
        return oid

    def get(self, order_id):
        return self.client.get(f"/api/orders/{order_id}").get_json()

    def patch(self, order_id, /, **body):
        return self.client.patch(f"/api/orders/{order_id}", json=body)

    def patch_item(self, order_id, item_id, /, **body):
        return self.client.patch(f"/api/orders/{order_id}/items/{item_id}", json=body)

    def status(self, order_id):
        return self.sql("SELECT status FROM orders WHERE id = ?", (order_id,))[0][0]

    def stock(self, product):
        return self.client.get(f"/api/products/{product['id']}").get_json()["stock_qty"]


class LineTotalTest(unittest.TestCase):
    def test_rounds_half_up_like_the_till(self):
        self.assertEqual(line_total_bani(2500, 101), 253)    # 252,5 bani — round() ar da 252
        self.assertEqual(line_total_bani(1250, 899), 1124)   # 1123,75
        self.assertEqual(line_total_bani(333, 1), 0)         # 0,333
        self.assertEqual(line_total_bani(3000, 450), 1350)


class CreateAndGetOrderTest(OrdersTestCase):
    def test_new_order_is_empty_and_pending(self):
        o = self.new_order()
        self.assertEqual(
            (o["status"], o["total_bani"], o["items"], o["item_count"], o["buyer_type"], o["customer_id"]),
            ("pending", 0, [], 0, "pf", None),
        )
        self.assertIs(o["fiscal_simulated"], False)
        self.assertEqual(self.get(o["id"]), o)

    def test_create_with_notes_and_company_buyer(self):
        o = self.new_order(notes=" Livrare ", buyer_type="pj", buyer_name="SC Test SRL", buyer_cui=VALID_CUI)
        self.assertEqual((o["notes"], o["buyer_type"], o["buyer_name"], o["buyer_cui"]),
                         ("Livrare", "pj", "SC Test SRL", VALID_CUI))

    def test_create_rejects_unknown_fields(self):
        self.assertError(self.client.post("/api/orders", json={"status": "paid"}), 400, "Câmpuri necunoscute: status")

    def test_missing_order(self):
        self.assertError(self.client.get("/api/orders/999"), 404, "Comanda nu există")


class ListOrdersTest(OrdersTestCase):
    def test_newest_first_with_item_count_and_no_lines(self):
        a = self.order((self.bread, 1000), (self.tomatoes, 500))
        b = self.order()
        body = self.client.get("/api/orders").get_json()
        self.assertEqual(body["total"], 2)
        self.assertEqual([(o["id"], o["item_count"]) for o in body["items"]], [(b, 0), (a, 2)])
        self.assertNotIn("items", body["items"][0])

    def test_status_filter_and_pagination(self):
        pending = self.order()
        cancelled = self.order()
        self.client.post(f"/api/orders/{cancelled}/cancel")
        ids = lambda **q: [o["id"] for o in self.client.get("/api/orders", query_string=q).get_json()["items"]]
        self.assertEqual(ids(status="pending"), [pending])
        self.assertEqual(ids(status="cancelled"), [cancelled])
        self.assertEqual(ids(limit=1, offset=1), [pending])

    def test_invalid_parameters(self):
        self.assertError(self.client.get("/api/orders?status=open"), 400, "pending, paid sau cancelled")
        self.assertError(self.client.get("/api/orders?status=paid,open"), 400, "pending, paid sau cancelled")
        self.assertError(self.client.get("/api/orders?limit=0"), 400, "cel puțin 1")
        self.assertError(self.client.get("/api/orders?date_from=19.10.2026"), 400, "AAAA-LL-ZZ")
        self.assertError(self.client.get("/api/orders?date_from=2026-10-02&date_to=2026-10-01"), 400, "este după")

    def ids(self, **query):
        r = self.client.get("/api/orders", query_string=query)
        self.assertEqual(r.status_code, 200, r.get_json())
        return [o["id"] for o in r.get_json()["items"]]

    def test_several_statuses(self):
        pending, cancelled, paid = self.order(), self.order(), self.order()
        self.client.post(f"/api/orders/{cancelled}/cancel")
        self.sql("UPDATE orders SET status = 'paid', payment_method = 'cash' WHERE id = ?", (paid,))
        self.assertEqual(self.ids(status="paid,cancelled"), [paid, cancelled])
        self.assertEqual(self.ids(), [paid, cancelled, pending])

    def test_day_filter_uses_payment_time(self):
        old, today = self.order(), self.order()
        self.sql("UPDATE orders SET status = 'paid', payment_method = 'cash', created_at = '2026-10-01 09:00:00', "
                 "fiscalized_at = '2026-10-02 10:00:00' WHERE id = ?", (old,))
        self.assertEqual(self.ids(date_from="2026-10-02", date_to="2026-10-02"), [old])
        self.assertEqual(self.ids(date_from="2026-10-01", date_to="2026-10-01"), [])  # creat pe 1, plătit pe 2
        self.assertEqual(self.ids(date_from="2026-10-03"), [today])
        self.assertEqual(self.ids(date_to="2026-10-02"), [old])

    def test_search_by_receipt_order_number_or_cui(self):
        a = self.order(buyer_type="pj", buyer_cui=VALID_CUI)
        b = self.order()
        self.sql("UPDATE orders SET status = 'paid', payment_method = 'card', fiscal_receipt_number = '57' WHERE id = ?", (b,))
        self.assertEqual(self.ids(q="57"), [b])
        self.assertEqual(self.ids(q=str(a)), [a])
        self.assertEqual(self.ids(q="1408"), [a])           # parte din CUI
        self.assertEqual(self.ids(q="ro1408"), [a])         # CUI-ul e salvat cu majuscule
        self.assertEqual(self.ids(q="%"), [])               # caracterele LIKE sunt literale
        self.assertEqual(self.ids(q="99999999999999999999"), [])


class AddItemTest(OrdersTestCase):
    def test_weighed_item_copies_product_and_updates_total(self):
        o = self.added(self.new_order()["id"], product_id=self.tomatoes["id"], quantity_milli=1250)
        item = o["items"][0]
        self.assertEqual(
            (item["product_id"], item["product_name"], item["sale_type"], item["quantity_milli"]),
            (self.tomatoes["id"], "Roșii", "weight", 1250),
        )
        self.assertEqual((item["list_price_bani"], item["unit_price_bani"], item["price_overridden"]), (899, 899, False))
        # TVA-ul e cota fixă a magazinului, copiată pe linie
        self.assertEqual((item["vat_fiscal_code"], item["vat_percent"], item["line_total_bani"]), ("A", 21.0, 1124))
        self.assertEqual((o["total_bani"], o["item_count"]), (1124, 1))

    def test_unit_item_defaults_to_one_piece(self):
        o = self.added(self.new_order()["id"], product_id=self.bread["id"])
        self.assertEqual((o["items"][0]["quantity_milli"], o["total_bani"]), (1000, 450))

    def test_same_product_same_price_is_merged(self):
        oid = self.order((self.bread, 1000), (self.tomatoes, 500))
        o = self.added(oid, product_id=self.bread["id"], quantity_milli=2000)
        self.assertEqual([(i["product_name"], i["quantity_milli"]) for i in o["items"]], [("Pâine", 3000), ("Roșii", 500)])
        self.assertEqual(o["total_bani"], 1350 + 450)

    def test_discounted_line_is_not_merged_with_a_new_one(self):
        oid = self.order((self.bread, 1000))
        line = self.get(oid)["items"][0]["id"]
        self.client.patch(f"/api/orders/{oid}/items/{line}", json={"discount_bp": 1000})
        o = self.added(oid, product_id=self.bread["id"])
        self.assertEqual([(i["unit_price_bani"], i["discount_bp"]) for i in o["items"]], [(405, 1000), (450, 0)])
        self.assertEqual(o["total_bani"], 855)

    def test_line_with_a_new_price_is_not_merged_with_a_new_one(self):
        oid = self.order((self.bread, 1000))
        line = self.get(oid)["items"][0]["id"]
        self.patch_item(oid, line, manual_price_bani=400)
        o = self.added(oid, product_id=self.bread["id"])
        self.assertEqual([(i["unit_price_bani"], i["price_overridden"]) for i in o["items"]], [(400, True), (450, False)])
        self.assertEqual(o["total_bani"], 850)

    def test_new_price_equal_to_the_catalog_is_still_not_merged(self):
        oid = self.order((self.bread, 1000))
        line = self.get(oid)["items"][0]["id"]
        self.patch_item(oid, line, manual_price_bani=450)
        o = self.added(oid, product_id=self.bread["id"])
        self.assertEqual([(i["manual_price_bani"], i["quantity_milli"]) for i in o["items"]], [(450, 1000), (None, 1000)])

    def test_line_is_a_snapshot_of_the_product(self):
        oid = self.order((self.bread, 1000))
        self.client.patch(f"/api/products/{self.bread['id']}", json={"name": "Pâine albă", "price_bani": 500})
        item = self.get(oid)["items"][0]
        self.assertEqual((item["product_name"], item["unit_price_bani"]), ("Pâine", 450))

    def test_adding_does_not_touch_stock(self):
        self.order((self.bread, 3000))
        self.assertEqual(self.stock(self.bread), 10)

    def test_product_must_be_sellable(self):
        oid = self.new_order()["id"]
        inactive = self.create(code="300", name="Vechi", active=False)
        self.assertError(self.add(oid, product_id=999), 400, "Produsul nu există")
        self.assertError(self.add(oid, product_id=inactive["id"], quantity_milli=1000), 400, "„Vechi” nu este activ")
        self.assertEqual(self.get(oid)["items"], [])

    def test_kg_sale_needs_a_price_per_kg(self):
        # la o instalare nouă prețul pe kg e 0 până îl setează magazinul
        self.sql("UPDATE products SET price_bani = 0 WHERE code = 'KG'")
        oid = self.new_order()["id"]
        self.assertError(self.add(oid, product_id=self.tomatoes["id"], quantity_milli=1000), 400,
                         "Prețul pe kilogram nu e setat")
        self.assertEqual(self.get(oid)["items"], [])

    def test_validation(self):
        oid = self.new_order()["id"]
        bread, tomatoes = self.bread["id"], self.tomatoes["id"]
        cases = [
            ({}, "'product_id' este obligatoriu"),
            ({"product_id": 10 ** 30}, "în afara intervalului"),
            ({"product_id": tomatoes}, "obligatoriu la produsele vândute la kg"),
            ({"product_id": bread, "quantity_milli": 1500}, "bucăți întregi"),
            ({"product_id": bread, "quantity_milli": 0}, "cel puțin 1"),
            ({"product_id": tomatoes, "quantity_milli": 1.25}, "număr întreg"),
            ({"product_id": tomatoes, "quantity_milli": 10_000_001}, "cel mult 10000000"),
            ({"product_id": bread, "unit_price_bani": 400}, "Câmpuri necunoscute: unit_price_bani"),
            ({"product_id": bread, "price": 400}, "Câmpuri necunoscute: price"),
        ]
        for body, message in cases:
            with self.subTest(body=body):
                self.assertError(self.add(oid, **body), 400, message)
        self.assertEqual(self.get(oid)["items"], [])

    def test_merge_cannot_exceed_line_limit(self):
        oid = self.order((self.tomatoes, 6_000_000))
        self.assertError(self.add(oid, product_id=self.tomatoes["id"], quantity_milli=5_000_000), 400, "cel mult")
        self.assertEqual(self.get(oid)["items"][0]["quantity_milli"], 6_000_000)

    def test_missing_order(self):
        self.assertError(self.add(999, product_id=self.bread["id"]), 404)


class ChangeItemTest(OrdersTestCase):
    def setUp(self):
        super().setUp()
        self.oid = self.order((self.bread, 1000), (self.tomatoes, 1000))
        self.bread_line, self.tomato_line = [i["id"] for i in self.get(self.oid)["items"]]

    def test_change_quantity(self):
        o = self.patch_item(self.oid, self.bread_line, quantity_milli=4000).get_json()
        self.assertEqual((o["items"][0]["quantity_milli"], o["items"][0]["line_total_bani"]), (4000, 1800))
        self.assertEqual(o["total_bani"], 1800 + 899)

    def test_discount_then_back_to_full_price(self):
        o = self.patch_item(self.oid, self.tomato_line, discount_bp=1000).get_json()  # 10%
        line = o["items"][1]
        self.assertEqual((line["discount_bp"], line["unit_price_bani"], line["price_overridden"], line["line_total_bani"]),
                         (1000, 809, True, 809))  # 8,99 − 10% = 8,091 → 8,09
        o = self.patch_item(self.oid, self.tomato_line, quantity_milli=2000).get_json()  # reducerea rămâne
        self.assertEqual((o["items"][1]["discount_bp"], o["items"][1]["line_total_bani"]), (1000, 1618))
        o = self.patch_item(self.oid, self.tomato_line, discount_bp=0).get_json()
        line = o["items"][1]
        self.assertEqual((line["discount_bp"], line["unit_price_bani"], line["price_overridden"]), (0, 899, False))
        self.assertEqual(o["total_bani"], 450 + 1798)

    def test_discounted_price_rounds_half_up_like_the_till(self):
        self.assertEqual([discounted_price(899, 1000), discounted_price(699, 1416), discounted_price(889, 5000),
                          discounted_price(450, 0), discounted_price(450, 1250)], [809, 600, 445, 450, 394])

    def test_discount_limits(self):
        self.assertError(self.patch_item(self.oid, self.bread_line, discount_bp=10_000), 400, "cel mult 9999")
        self.assertError(self.patch_item(self.oid, self.bread_line, discount_bp=-1), 400, "cel puțin 0")
        self.assertError(self.patch_item(self.oid, self.bread_line, discount_bp=12.5), 400, "număr întreg")
        self.assertError(self.patch_item(self.oid, self.bread_line, discount_bp=9_999), 400, "prețul ar ajunge la 0 lei")
        self.assertEqual(self.get(self.oid)["items"][0]["unit_price_bani"], 450)

    def price_parts(self, order, index):
        line = order["items"][index]
        return (line["list_price_bani"], line["manual_price_bani"], line["discount_bp"], line["unit_price_bani"],
                line["line_total_bani"], line["price_overridden"])

    def test_new_price_then_a_discount_on_it(self):
        # produsul A: 120 lei în catalog → preț nou 100 → reducere 30% → 70 lei pe bon
        product_a = self.create(code="500", name="Produs A", price_bani=12000)
        oid = self.order((product_a, 1000))
        line = self.get(oid)["items"][0]["id"]
        o = self.patch_item(oid, line, manual_price_bani=10000).get_json()
        self.assertEqual(self.price_parts(o, 0), (12000, 10000, 0, 10000, 10000, True))
        o = self.patch_item(oid, line, discount_bp=3000).get_json()
        self.assertEqual(self.price_parts(o, 0), (12000, 10000, 3000, 7000, 7000, True))
        self.assertEqual(o["total_bani"], 7000)
        o = self.patch_item(oid, line, discount_bp=2000).get_json()  # din 100, nu din 70: fără reduceri în lanț
        self.assertEqual(self.price_parts(o, 0)[3], 8000)
        o = self.patch_item(oid, line, quantity_milli=3000).get_json()  # cantitatea nu atinge prețul
        self.assertEqual(self.price_parts(o, 0), (12000, 10000, 2000, 8000, 24000, True))
        o = self.patch_item(oid, line, discount_bp=0).get_json()  # fără reducere: rămâne prețul nou
        self.assertEqual(self.price_parts(o, 0)[1:4], (10000, 0, 10000))
        self.assertEqual(self.client.get(f"/api/products/{product_a['id']}").get_json()["price_bani"], 12000)

    def test_discount_first_then_new_price_gives_the_same(self):
        product_a = self.create(code="500", name="Produs A", price_bani=12000)
        oid = self.order((product_a, 1000))
        line = self.get(oid)["items"][0]["id"]
        o = self.patch_item(oid, line, discount_bp=3000).get_json()
        self.assertEqual(self.price_parts(o, 0)[1:4], (None, 3000, 8400))  # 120 − 30%
        o = self.patch_item(oid, line, manual_price_bani=10000).get_json()  # reducerea rămâne, pe prețul nou
        self.assertEqual(self.price_parts(o, 0)[1:4], (10000, 3000, 7000))
        o = self.patch_item(oid, line, manual_price_bani=None).get_json()  # înapoi la catalog, reducerea rămâne
        self.assertEqual(self.price_parts(o, 0)[1:4], (None, 3000, 8400))

    def test_new_price_and_discount_in_one_request(self):
        o = self.patch_item(self.oid, self.tomato_line, manual_price_bani=750, discount_bp=1000).get_json()
        self.assertEqual(self.price_parts(o, 1), (899, 750, 1000, 675, 675, True))  # 7,50 − 10% la 1 kg
        o = self.patch_item(self.oid, self.tomato_line, manual_price_bani=None, discount_bp=0).get_json()  # „Preț din catalog”
        self.assertEqual(self.price_parts(o, 1), (899, None, 0, 899, 899, False))
        self.assertEqual(o["total_bani"], 450 + 899)

    def test_new_price_can_be_higher_than_the_catalog(self):
        o = self.patch_item(self.oid, self.bread_line, manual_price_bani=600).get_json()
        self.assertEqual(self.price_parts(o, 0)[1:4], (600, 0, 600))
        # 6,00 − 25% = 4,50: exact prețul din catalog, dar linia tot e modificată
        o = self.patch_item(self.oid, self.bread_line, discount_bp=2500).get_json()
        self.assertEqual(self.price_parts(o, 0), (450, 600, 2500, 450, 450, True))

    def test_new_price_limits(self):
        self.assertError(self.patch_item(self.oid, self.bread_line, manual_price_bani=0), 400, "cel puțin 1")
        self.assertError(self.patch_item(self.oid, self.bread_line, manual_price_bani=100_000_000), 400,
                         "cel mult 99999999")
        self.assertError(self.patch_item(self.oid, self.bread_line, manual_price_bani=4.5), 400, "număr întreg")
        self.assertError(self.patch_item(self.oid, self.bread_line, manual_price_bani="100"), 400, "număr întreg")
        self.assertError(self.patch_item(self.oid, self.bread_line, unit_price_bani=400), 400, "Câmpuri necunoscute")
        self.patch_item(self.oid, self.bread_line, manual_price_bani=1)  # 0,01 lei
        # 0,01 − 50% = 0,005 → rotunjit în sus, 0,01 (ca pe casă); 99,99% duce la 0 → refuzat
        self.assertEqual(self.price_parts(self.patch_item(self.oid, self.bread_line, discount_bp=5000).get_json(), 0)[3], 1)
        self.patch_item(self.oid, self.bread_line, discount_bp=0)
        self.assertError(self.patch_item(self.oid, self.bread_line, discount_bp=9999), 400, "prețul ar ajunge la 0 lei")
        self.assertEqual(self.price_parts(self.get(self.oid), 0)[1:4], (1, 0, 1))

    def test_delete_line(self):
        r = self.client.delete(f"/api/orders/{self.oid}/items/{self.bread_line}")
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(([i["product_name"] for i in r.get_json()["items"]], r.get_json()["total_bani"]), (["Roșii"], 899))

    def test_errors(self):
        other = self.order((self.bread, 1000))
        other_line = self.get(other)["items"][0]["id"]
        self.assertError(self.patch_item(self.oid, self.bread_line), 400, "Nimic de modificat")
        self.assertError(self.patch_item(self.oid, self.bread_line, quantity_milli=500), 400, "bucăți întregi")
        self.assertError(self.patch_item(self.oid, self.bread_line, quantity_milli=None), 400, "număr întreg")
        self.assertError(self.patch_item(self.oid, other_line, quantity_milli=2000), 404, "nu există pe această comandă")
        self.assertError(self.client.delete(f"/api/orders/{self.oid}/items/{other_line}"), 404)
        self.assertError(self.patch_item(self.oid, 999, quantity_milli=2000), 404)
        self.assertEqual(self.get(other)["items"][0]["quantity_milli"], 1000)


class BuyerTest(OrdersTestCase):
    def customer(self, type_, name, cui=None):
        self.sql("INSERT INTO customers (type, name, cui) VALUES (?, ?, ?)", (type_, name, cui))
        return self.sql("SELECT MAX(id) FROM customers")[0][0]

    def buyer(self, order):
        return order["customer_id"], order["buyer_type"], order["buyer_name"], order["buyer_cui"]

    def test_saved_customer_is_copied(self):
        cid = self.customer("pj", "SC Legume SRL", VALID_CUI)
        o = self.patch(self.new_order()["id"], customer_id=cid).get_json()
        self.assertEqual(self.buyer(o), (cid, "pj", "SC Legume SRL", VALID_CUI))

    def test_removing_customer_resets_to_anonymous(self):
        cid = self.customer("pj", "SC Legume SRL", VALID_CUI)
        oid = self.new_order(customer_id=cid)["id"]
        self.assertEqual(self.buyer(self.patch(oid, customer_id=None).get_json()), (None, "pf", "", ""))

    def test_typed_buyer_replaces_saved_customer(self):
        cid = self.customer("pj", "SC Legume SRL", VALID_CUI)
        oid = self.new_order(customer_id=cid)["id"]
        o = self.patch(oid, buyer_type="pj", buyer_cui=" ro 1439 9840 ").get_json()
        self.assertEqual(self.buyer(o), (None, "pj", "", "RO14399840"))
        o = self.patch(oid, buyer_type="pf", buyer_name="Ion Popescu").get_json()
        self.assertEqual(self.buyer(o), (None, "pf", "Ion Popescu", ""))

    def test_notes_alone_keep_buyer(self):
        oid = self.new_order(buyer_type="pj", buyer_cui=VALID_CUI)["id"]
        o = self.patch(oid, notes="Factură cerută").get_json()
        self.assertEqual((o["notes"], o["buyer_cui"]), ("Factură cerută", VALID_CUI))

    def test_validation(self):
        oid = self.new_order()["id"]
        cases = [
            ({}, "Nimic de modificat"),
            ({"customer_id": 999}, "Clientul nu există"),
            ({"customer_id": 1, "buyer_type": "pj"}, "nu ambele"),
            ({"buyer_name": "SC X SRL"}, "'buyer_type' este obligatoriu"),
            ({"buyer_type": "pj"}, "'buyer_cui' este obligatoriu"),
            ({"buyer_type": "pj", "buyer_cui": "RO14080701"}, "nu este un cod fiscal (CUI) valid"),
            ({"buyer_type": "pj", "buyer_cui": "ABC"}, "nu este un cod fiscal"),
            ({"buyer_type": "pf", "buyer_cui": VALID_CUI}, "doar pentru persoană juridică"),
            ({"buyer_type": "srl"}, "unul dintre: pf, pj"),
            ({"notes": "x" * 501}, "cel mult 500"),
        ]
        for body, message in cases:
            with self.subTest(body=body):
                self.assertError(self.patch(oid, **body), 400, message)
        self.assertEqual(self.buyer(self.get(oid)), (None, "pf", "", ""))


class CancelAndLockedOrdersTest(OrdersTestCase):
    def test_cancel(self):
        oid = self.order((self.bread, 2000))
        r = self.client.post(f"/api/orders/{oid}/cancel")
        self.assertEqual((r.status_code, r.get_json()["status"]), (200, "cancelled"))
        self.assertEqual(self.stock(self.bread), 10)

    def test_cancelled_and_paid_orders_cannot_change(self):
        cancelled = self.order((self.bread, 1000))
        self.client.post(f"/api/orders/{cancelled}/cancel")
        paid = self.order((self.bread, 1000))
        self.sql("UPDATE orders SET status = 'paid', payment_method = 'cash' WHERE id = ?", (paid,))
        for oid, message in ((cancelled, "anulată"), (paid, "deja plătită")):
            line = self.get(oid)["items"][0]["id"]
            attempts = [
                self.add(oid, product_id=self.bread["id"]),
                self.patch_item(oid, line, quantity_milli=5000),
                self.client.delete(f"/api/orders/{oid}/items/{line}"),
                self.patch(oid, notes="x"),
                self.client.post(f"/api/orders/{oid}/cancel"),
            ]
            for r in attempts:
                with self.subTest(oid=oid, url=r.request.path, method=r.request.method):
                    self.assertError(r, 409, message)
            self.assertEqual(self.get(oid)["items"][0]["quantity_milli"], 1000)

    def test_cancel_missing_order(self):
        self.assertError(self.client.post("/api/orders/999/cancel"), 404)


if __name__ == "__main__":
    unittest.main()
