import unittest

import database
from tests.helpers import ApiTestCase

BASE = {"code": "101", "name": "Roșii", "price_bani": 899}  # produs din catalog = la bucată


class ProductsTestCase(ApiTestCase):
    def post_product(self, **overrides):
        return self.client.post("/api/products", json={**BASE, **overrides})

    def create(self, **overrides):
        r = self.post_product(**overrides)
        self.assertEqual(r.status_code, 201, r.get_json())
        return r.get_json()

    def kg(self, price_bani=899, name="Roșii"):
        """Vânzarea la kilogram (rândul fix KG), cu prețul pe kg și denumirea date."""
        r = self.client.patch("/api/products/kg", json={"name": name, "price_bani": price_bani})
        self.assertEqual(r.status_code, 200, r.get_json())
        return r.get_json()

    def listing(self, **params):
        r = self.client.get("/api/products", query_string=params)
        self.assertEqual(r.status_code, 200, r.get_json())
        return r.get_json()

    def names(self, **params):
        return [p["name"] for p in self.listing(**params)["items"]]

    def sql(self, statement, params=()):
        conn = database.get_db()
        rows = conn.execute(statement, params).fetchall()
        conn.commit()
        conn.close()
        return rows


class CreateProductTest(ProductsTestCase):
    def test_create_minimal(self):
        p = self.create()
        self.assertEqual((p["code"], p["name"], p["sale_type"], p["price_bani"]), ("101", "Roșii", "unit", 899))
        self.assertIsNone(p["barcode"])
        self.assertEqual((p["stock_qty"], p["min_stock_qty"]), (0, 0))
        self.assertIs(p["active"], True)
        self.assertIs(p["low_stock"], False)

    def test_text_is_trimmed_and_empty_barcode_is_null(self):
        a = self.create(code=" 102 ", name="  Pâine  ", barcode="")
        b = self.create(code="103", barcode="   ")  # al doilea produs fără cod de bare — fără conflict
        self.assertEqual((a["code"], a["name"], a["barcode"]), ("102", "Pâine", None))
        self.assertIsNone(b["barcode"])

    def test_initial_stock_is_recorded_as_receipt(self):
        p = self.create(initial_stock_qty=5)
        self.assertEqual(p["stock_qty"], 5)
        rows = self.sql("SELECT delta_qty, reason, note FROM stock_movements WHERE product_id = ?", (p["id"],))
        self.assertEqual([tuple(r) for r in rows], [(5, "receipt", "Stoc inițial")])

    def test_zero_initial_stock_records_nothing(self):
        self.create(initial_stock_qty=0)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM stock_movements")[0][0], 0)

    def test_required_fields(self):
        for field in ("code", "name", "price_bani"):
            body = dict(BASE)
            del body[field]
            with self.subTest(field=field):
                self.assertError(self.client.post("/api/products", json=body), 400, f"'{field}' este obligatoriu")

    def test_field_validation(self):
        cases = [
            ({"price_bani": 8.99}, "număr întreg"),
            ({"price_bani": "899"}, "număr întreg"),
            ({"price_bani": True}, "număr întreg"),
            ({"price_bani": -1}, "cel puțin 0"),
            ({"price_bani": 100_000_000}, "cel mult 99999999"),
            ({"sale_type": "weight"}, "Câmpuri necunoscute: sale_type"),  # catalogul e doar la bucată
            ({"name": 123}, "trebuie să fie text"),
            ({"name": "x" * 201}, "cel mult 200"),
            ({"code": ""}, "nu poate fi gol"),
            ({"active": "da"}, "true sau false"),
            ({"initial_stock_qty": -3}, "cel puțin 0"),
        ]
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                self.assertError(self.post_product(**overrides), 400, message)

    def test_unknown_fields_are_rejected(self):
        self.assertError(self.post_product(price=8.99), 400, "Câmpuri necunoscute: price")

    def test_stock_cannot_be_set_directly(self):
        self.assertError(self.post_product(stock_qty=5), 400, "initial_stock_qty")

    def test_vat_is_fixed_not_chosen_per_product(self):
        # O singură cotă, 21%, pentru tot (fiscal.VAT_PERCENT) — produsul nu are TVA
        self.assertError(self.post_product(vat_rate_id=1), 400, "Câmpuri necunoscute: vat_rate_id")
        self.assertFalse({"vat_rate_id", "vat_fiscal_code", "vat_percent"} & self.create().keys())
        self.assertEqual(self.client.get("/api/vat-rates").status_code, 404)

    def test_duplicate_code_and_barcode(self):
        self.create(code="101", barcode="5941234567890")
        self.assertError(self.post_product(code="101"), 409, "codul „101”")
        self.assertError(self.post_product(code="102", barcode="5941234567890"), 409, "codul de bare „5941234567890”")


class GetAndLookupTest(ProductsTestCase):
    def test_get(self):
        p = self.create()
        self.assertEqual(self.client.get(f"/api/products/{p['id']}").get_json(), p)
        self.assertError(self.client.get("/api/products/999"), 404, "Produsul nu există")

    def test_lookup_by_code_or_barcode(self):
        p = self.create(code="101", barcode="5941234567890")
        self.assertEqual(self.client.get("/api/products/lookup?code=101").get_json()["id"], p["id"])
        self.assertEqual(self.client.get("/api/products/lookup?code=5941234567890").get_json()["id"], p["id"])
        self.assertError(self.client.get("/api/products/lookup?code=999"), 404, "„999”")
        self.assertError(self.client.get("/api/products/lookup"), 400, "'code'")

    def test_lookup_prefers_code_over_barcode(self):
        self.create(code="1", barcode="777")
        by_code = self.create(code="777")
        self.assertEqual(self.client.get("/api/products/lookup?code=777").get_json()["id"], by_code["id"])

    def test_lookup_ignores_inactive_products(self):
        self.create(code="101", active=False)
        self.assertError(self.client.get("/api/products/lookup?code=101"), 404)


class ListProductsTest(ProductsTestCase):
    def test_sorted_by_name_ignoring_diacritics(self):
        for code, name in [("1", "Roșii"), ("2", "Ardei"), ("3", "Ălune"), ("4", "Brânză")]:
            self.create(code=code, name=name)
        self.assertEqual(self.names(), ["Ălune", "Ardei", "Brânză", "Roșii"])

    def test_search_ignores_diacritics_and_case(self):
        self.create(code="1", name="Roșii")
        self.create(code="2", name="Ardei")
        for q in ("rosii", "ROȘII", "Rosii", "roș", "osi"):
            with self.subTest(q=q):
                self.assertEqual(self.names(q=q), ["Roșii"])

    def test_search_needs_every_word(self):
        self.create(code="1", name="Roșii cherry")
        self.create(code="2", name="Roșii")
        self.create(code="3", name="Ardei cherry")
        self.assertEqual(self.names(q="cherry rosii"), ["Roșii cherry"])

    def test_exact_code_first_then_code_prefix_then_name(self):
        self.create(code="10", name="Zmeură")
        self.create(code="101", name="Ardei")
        self.create(code="7", name="Suc 10 lei")
        self.create(code="8", name="Mere")
        self.assertEqual(self.names(q="10"), ["Zmeură", "Ardei", "Suc 10 lei"])

    def test_search_by_barcode(self):
        self.create(code="1", name="Lapte", barcode="5941234567890")
        self.create(code="2", name="Iaurt")
        self.assertEqual(self.names(q="5941234567890"), ["Lapte"])

    def test_search_treats_like_wildcards_literally(self):
        self.create(code="1", name="Ciocolată 70%")
        self.create(code="2", name="Ciocolată albă")
        self.assertEqual(self.names(q="70%"), ["Ciocolată 70%"])
        self.assertEqual(self.names(q="%"), ["Ciocolată 70%"])
        self.assertEqual(self.names(q="_"), [])

    def test_filters(self):
        self.create(code="1", name="Roșii")
        self.create(code="2", name="Pâine")
        self.create(code="3", name="Vechi", active=False)
        self.assertEqual(self.names(), ["Pâine", "Roșii"])  # implicit doar cele active
        self.assertEqual(self.names(active="0"), ["Vechi"])
        self.assertEqual(self.names(active="all"), ["Pâine", "Roșii", "Vechi"])

    def test_low_stock(self):
        low = self.create(code="1", name="Făină", min_stock_qty=5, initial_stock_qty=3)
        self.create(code="2", name="Griș", min_stock_qty=4, initial_stock_qty=4)   # exact la prag → scăzut
        self.create(code="3", name="Mălai", min_stock_qty=2, initial_stock_qty=10)
        self.create(code="4", name="Orez")  # fără prag minim → niciodată scăzut
        self.assertIs(low["low_stock"], True)
        self.assertEqual(self.names(low_stock="1"), ["Făină", "Griș"])

    def test_pagination(self):
        for i in range(3):
            self.create(code=str(i), name=f"Produs {i}")
        page = self.listing(limit=2)
        self.assertEqual((len(page["items"]), page["total"], page["limit"], page["offset"]), (2, 3, 2, 0))
        self.assertEqual(self.names(limit=2, offset=2), ["Produs 2"])

    def test_invalid_parameters(self):
        cases = [
            ({"limit": 0}, "cel puțin 1"),
            ({"limit": 501}, "cel mult 500"),
            ({"limit": "abc"}, "număr întreg"),
            ({"offset": -1}, "cel puțin 0"),
            ({"active": "da"}, "0, 1 sau all"),
        ]
        for params, message in cases:
            with self.subTest(params=params):
                self.assertError(self.client.get("/api/products", query_string=params), 400, message)


class KgSaleTest(ProductsTestCase):
    """Un singur preț pe kilogram, pentru orice marfă vândută la kg."""

    def test_exists_from_the_start_without_a_price(self):
        kg = self.client.get("/api/products/kg").get_json()
        self.assertEqual((kg["code"], kg["name"], kg["sale_type"], kg["price_bani"], kg["active"]),
                         ("KG", "Marfă la kilogram", "weight", 0, True))

    def test_set_price_and_receipt_name(self):
        kg = self.kg(1250, "Haine la kg")
        self.assertEqual((kg["name"], kg["price_bani"]), ("Haine la kg", 1250))
        r = self.client.patch("/api/products/kg", json={"price_bani": 1300})
        self.assertEqual((r.get_json()["name"], r.get_json()["price_bani"]), ("Haine la kg", 1300))
        # la casă se poate și tasta: KG + Enter
        self.assertEqual(self.client.get("/api/products/lookup?code=KG").get_json()["price_bani"], 1300)

    def test_validation(self):
        for body, message in [({}, "Nimic de modificat"), ({"price_bani": 0}, "cel puțin 1"),
                              ({"price_bani": 12.5}, "număr întreg"), ({"name": ""}, "nu poate fi gol"),
                              ({"sale_type": "unit"}, "Câmpuri necunoscute"), ({"code": "X"}, "Câmpuri necunoscute")]:
            with self.subTest(body=body):
                self.assertError(self.client.patch("/api/products/kg", json=body), 400, message)

    def test_not_part_of_the_catalog(self):
        kg = self.kg()
        self.create(code="200", name="Pâine")
        self.assertEqual(self.names(active="all"), ["Pâine"])
        for r in (self.client.patch(f"/api/products/{kg['id']}", json={"active": False}),
                  self.client.delete(f"/api/products/{kg['id']}"),
                  self.client.post(f"/api/products/{kg['id']}/stock", json={"delta_qty": 1, "reason": "receipt"})):
            self.assertError(r, 400, "Produse → La kilogram")
        self.assertError(self.post_product(code="KG"), 409, "codul „KG”")
        self.assertIs(self.client.get("/api/products/kg").get_json()["active"], True)


class UpdateProductTest(ProductsTestCase):
    def test_partial_update(self):
        p = self.create()
        r = self.client.patch(f"/api/products/{p['id']}", json={"price_bani": 999})
        self.assertEqual(r.status_code, 200, r.get_json())
        updated = r.get_json()
        self.assertEqual(updated["price_bani"], 999)
        for key in ("code", "name", "sale_type", "stock_qty", "active"):
            self.assertEqual(updated[key], p[key], key)

    def test_rename_updates_search(self):
        p = self.create(name="Roșii")
        self.client.patch(f"/api/products/{p['id']}", json={"name": "Ardei kapia"})
        self.assertEqual(self.names(q="kapia"), ["Ardei kapia"])
        self.assertEqual(self.names(q="rosii"), [])

    def test_clear_barcode(self):
        p = self.create(barcode="123")
        r = self.client.patch(f"/api/products/{p['id']}", json={"barcode": None})
        self.assertIsNone(r.get_json()["barcode"])

    def test_departments_no_longer_exist(self):
        # Categoriile sunt fixe (sale_type) — nu mai există raioane
        self.assertError(self.post_product(department_id=1), 400, "Câmpuri necunoscute: department_id")
        self.assertNotIn("department_id", self.create())
        self.assertEqual(self.client.get("/api/departments").status_code, 404)

    def test_keeping_own_code_is_not_a_duplicate(self):
        p = self.create(code="101")
        r = self.client.patch(f"/api/products/{p['id']}", json={"code": "101", "name": "Roșii românești"})
        self.assertEqual(r.status_code, 200, r.get_json())

    def test_stock_cannot_be_patched(self):
        p = self.create()
        r = self.client.patch(f"/api/products/{p['id']}", json={"stock_qty": 50})
        self.assertError(r, 400, f"POST /api/products/{p['id']}/stock")

    def test_update_errors(self):
        p = self.create(code="101")
        self.create(code="102")
        url = f"/api/products/{p['id']}"
        self.assertError(self.client.patch(url, json={}), 400, "Nimic de modificat")
        self.assertError(self.client.patch(url, json={"code": "102"}), 409, "codul „102”")
        self.assertError(self.client.patch(url, json={"vat_rate_id": 1}), 400, "Câmpuri necunoscute: vat_rate_id")
        self.assertError(self.client.patch(url, json={"name": ""}), 400, "nu poate fi gol")
        self.assertError(self.client.patch(url, json={"price": 1}), 400, "Câmpuri necunoscute: price")
        self.assertError(self.client.patch("/api/products/999", json={"name": "X"}), 404)


class DeleteProductTest(ProductsTestCase):
    def test_unused_product_is_deleted_for_good(self):
        p = self.create(code="101")
        self.assertEqual(self.client.delete(f"/api/products/{p['id']}").get_json(), {"deleted": "hard"})
        self.assertError(self.client.get(f"/api/products/{p['id']}"), 404)
        self.create(code="101")  # codul se poate refolosi

    def test_product_with_history_is_only_deactivated(self):
        p = self.create(code="101", initial_stock_qty=5)
        body = self.client.delete(f"/api/products/{p['id']}").get_json()
        self.assertEqual(body["deleted"], "soft")
        self.assertIs(body["product"]["active"], False)
        self.assertEqual(body["product"]["stock_qty"], 5)
        self.assertEqual(self.names(), [])
        self.assertEqual(self.names(active="0"), ["Roșii"])
        self.assertError(self.client.get("/api/products/lookup?code=101"), 404)
        r = self.client.patch(f"/api/products/{p['id']}", json={"active": True})  # reactivare
        self.assertIs(r.get_json()["active"], True)

    def test_delete_missing(self):
        self.assertError(self.client.delete("/api/products/999"), 404)


if __name__ == "__main__":
    unittest.main()
