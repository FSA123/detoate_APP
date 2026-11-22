import io
import unittest

from openpyxl import Workbook, load_workbook

from tests.test_products import ProductsTestCase
from tests.test_reports import SalesTestCase

HEADER = ["Cod", "Cod de bare", "Denumire", "Preț (lei)", "Stoc (buc)", "Stoc minim", "Activ"]


def xlsx(*rows):
    workbook = Workbook()
    for row in rows:
        workbook.active.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def sheet_rows(content, sheet=0):
    return [list(r) for r in load_workbook(io.BytesIO(content)).worksheets[sheet].iter_rows(values_only=True)]


class ExcelTestCase(ProductsTestCase):
    def upload(self, content, filename="produse.xlsx"):
        return self.client.post("/api/excel/products", data={"file": (io.BytesIO(content), filename)},
                                content_type="multipart/form-data")

    def imported(self, *rows):
        r = self.upload(xlsx(*rows))
        self.assertEqual(r.status_code, 200, r.get_json())
        return r.get_json()

    def product(self, code):
        return self.client.get("/api/products/lookup", query_string={"code": code}).get_json()

    def all_products(self):
        return self.listing(active="all", limit=500)["items"]


class ExportProductsTest(ExcelTestCase):
    def test_export_in_the_import_format(self):
        self.kg(1299)  # vânzarea la kilogram nu e un produs din catalog: nu apare
        self.create(code="0101", barcode="5940000000011", min_stock_qty=2, initial_stock_qty=7)
        self.create(code="200", name="Pâine", price_bani=450, active=False)
        r = self.client.get("/api/excel/products")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.mimetype, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertIn("produse.xlsx", r.headers["Content-Disposition"])
        rows = sheet_rows(r.data)
        self.assertEqual(rows[0], HEADER)
        self.assertEqual(rows[1:], [
            ["200", None, "Pâine", 4.5, 0, 0, "nu"],
            ["0101", "5940000000011", "Roșii", 8.99, 7, 2, "da"],  # zeroul din față rămâne
        ])

    def test_round_trip_changes_only_what_was_edited(self):
        self.create(code="101")
        self.create(code="200", name="Pâine", price_bani=450, initial_stock_qty=10)
        workbook = load_workbook(io.BytesIO(self.client.get("/api/excel/products").data))
        workbook.active["D3"] = 4.75  # Roșii e pe rândul 3 (ordonat după nume)
        buffer = io.BytesIO()
        workbook.save(buffer)
        r = self.upload(buffer.getvalue())
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual({k: r.get_json()[k] for k in ("created", "updated", "unchanged", "stock_ignored")},
                         {"created": 0, "updated": 1, "unchanged": 1, "stock_ignored": 0})
        self.assertEqual(self.product("101")["price_bani"], 475)

    def test_round_trip_with_negative_stock(self):
        # vândut înainte de recepție → stoc negativ în export; reimportul nu trebuie să-l refuze
        p = self.create(code="200", name="Pâine", price_bani=450)
        self.client.post(f"/api/products/{p['id']}/stock", json={"delta_qty": -3, "reason": "adjustment"})
        r = self.upload(self.client.get("/api/excel/products").data)
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual((r.get_json()["unchanged"], self.product("200")["stock_qty"]), (1, -3))
        # la un produs nou, stocul inițial negativ rămâne o greșeală
        self.assertEqual(self.upload(xlsx(HEADER[:5], ["201", None, "Covrigi", 1.5, -2])).get_json()["errors"],
                         [{"row": 2, "message": "Stoc: „-2” nu este un număr întreg pozitiv"}])


class ImportProductsTest(ExcelTestCase):
    def test_new_products_with_aliases_and_any_column_order(self):
        body = self.imported(
            # „Raion” și TVA-ul din fișierele vechi nu mai înseamnă nimic: coloane ignorate
            ["Nume", "COD", "pret", "Cota TVA", "UM", "Raion", "Stoc", "Observații"],
            ["Apă plată 2 L", 500.0, "3,49", "11%", "Buc", "Băuturi", 24, "rafturi"],
            ["Covrigi", "201", 1.5, "b", "La bucată", None, None, None],
            ["Suc", "202", 4, None, None, None, None, None],          # UM gol = la bucată
        )
        self.assertEqual(body, {"created": 3, "updated": 0, "unchanged": 0, "stock_ignored": 0,
                                "ignored_columns": ["Cota TVA", "Raion", "Observații"], "auto_codes": None})
        water = self.product("500")
        self.assertEqual((water["name"], water["sale_type"], water["price_bani"], water["stock_qty"], water["active"]),
                         ("Apă plată 2 L", "unit", 349, 24, True))
        self.assertEqual({p["sale_type"] for p in self.all_products()}, {"unit"})
        self.assertEqual(self.names(q="apa plata"), ["Apă plată 2 L"])  # căutarea fără diacritice merge
        movements = self.client.get(f"/api/products/{water['id']}/movements").get_json()["items"]
        self.assertEqual([(m["delta_qty"], m["reason"]) for m in movements], [(24, "receipt")])

    def test_kg_products_are_refused_there_is_one_price_per_kg(self):
        r = self.upload(xlsx(["Cod", "Denumire", "UM", "Preț (lei)"],
                             ["104", "Banane", "kg", 6.99], ["105", "Cartofi", "la kilogram", 3.49],
                             ["KG", "Marfă", "buc", 1], ["106", "Ulei", "litri", 9]))
        self.assertError(r, 400, "Fișierul are 4 erori")
        self.assertEqual([(e["row"], e["message"]) for e in r.get_json()["errors"]], [
            (2, "Categorie: „kg” — produsele la kg nu se importă: la kilogram e un singur preț, setat în Produse → La kilogram"),
            (3, "Categorie: „la kilogram” — produsele la kg nu se importă: la kilogram e un singur preț, setat în Produse → La kilogram"),
            (4, "Codul „KG” e rezervat pentru vânzarea la kilogram"),
            (5, "Categorie: „litri” — aici sunt doar produse la bucată (buc)"),
        ])
        self.assertEqual(self.all_products(), [])

    def test_existing_products_are_updated_and_stock_is_left_to_movements(self):
        self.create(code="101", barcode="111", initial_stock_qty=5)
        body = self.imported(HEADER, ["101", None, "Roșii cherry", 12.99, 50, 3, "nu"])
        self.assertEqual((body["updated"], body["stock_ignored"]), (1, 1))
        # celula goală de cod de bare îl șterge; stocul rămâne cel din registru (5), nu 50
        p = next(p for p in self.all_products() if p["code"] == "101")
        self.assertEqual((p["name"], p["price_bani"], p["barcode"], p["stock_qty"], p["min_stock_qty"], p["active"]),
                         ("Roșii cherry", 1299, None, 5, 3, False))

    def test_missing_optional_columns_are_left_alone(self):
        self.create(code="101", barcode="111", min_stock_qty=4)
        # capul de tabel din exporturile vechi („Vânzare”) e încă recunoscut; coloana TVA se ignoră
        body = self.imported(["Cod", "Denumire", "Vânzare (kg/buc)", "Preț (lei)", "TVA"], ["101", "Roșii", "buc", 9.5, "B"])
        self.assertEqual(body["ignored_columns"], ["TVA"])
        p = self.product("101")
        self.assertEqual((p["price_bani"], p["barcode"], p["min_stock_qty"]), (950, "111", 4))

    def test_float_noise_from_formulas_is_tolerated(self):
        self.imported(HEADER[:4], ["1", None, "X", 0.1 + 0.2])
        self.assertEqual(self.product("1")["price_bani"], 30)

    def test_row_errors_are_all_reported_and_nothing_is_written(self):
        self.create(code="900", barcode="5940000000028")
        r = self.upload(xlsx(
            HEADER[:5],
            ["1", None, "Bun", 1],
            ["2", None, "Preț greșit", "doi lei"],
            ["3", None, "Zecimale", 1.234],
            ["4", None, "Stoc", 1, "multe"],
            ["1", None, "Dublură", 1],
            ["KG", None, "Rezervat", 1],
            [None, None, "Fără cod", 1],
            ["6", "5940000000028", "Cod de bare luat", 1],
            ["7", None, None, 1],
            [None, None, None, None, None],          # rând gol: ignorat
            ["8", None, "Negativ", -1],
        ))
        self.assertError(r, 400, "Fișierul are 9 erori — nu s-a importat nimic")
        self.assertEqual([(e["row"], e["message"]) for e in r.get_json()["errors"]], [
            (3, "Preț: „doi lei” nu este un număr"),
            (4, "Preț: „1.234” are mai mult de două zecimale"),
            (5, "Stoc: „multe” nu este un număr întreg pozitiv"),
            (6, "Codul „1” apare și pe rândul 2"),
            (7, "Codul „KG” e rezervat pentru vânzarea la kilogram"),
            (8, "Cod lipsește"),
            (9, "Codul de bare „5940000000028” e deja al produsului 900"),
            (10, "Denumirea lipsește"),
            (12, "Preț: trebuie să fie între 0 și 999999 lei"),
        ])
        self.assertEqual([p["code"] for p in self.all_products()], ["900"])

    def test_barcode_can_move_between_products_in_the_same_file(self):
        self.create(code="1", barcode="777")
        self.create(code="2")
        self.imported(HEADER[:4], ["1", None, "Unu", 1], ["2", "777", "Doi", 1])
        self.assertEqual(self.product("777")["code"], "2")

    def test_bad_files(self):
        self.assertError(self.client.post("/api/excel/products"), 400, "câmpul 'file'")
        self.assertError(self.upload(b"nu e excel", "produse.pdf"), 400, "nu este un document Excel .xlsx valid (sau un .csv)")
        self.assertError(self.upload(xlsx(["Cod", "Denumire"], ["1", "X"])), 400,
                         "Lipsesc coloanele: Preț (lei)")
        self.assertError(self.upload(xlsx(HEADER)), 400, "nu conține niciun produs")


class StoreListTest(ExcelTestCase):
    """Lista magazinului, așa cum e: CSV sau .xlsx, fără coduri, cu capetele altui program."""

    HEADER = "Denumire Produs;Cantitate Produs;Pret Vanzare\r\n"

    def csv(self, text, encoding="cp1250", filename="produse.csv"):
        return self.upload(text.encode(encoding), filename)

    def test_csv_from_romanian_excel_without_codes(self):
        # Excel în română: „;” între coloane, virgulă zecimală, codare Windows (cp1250)
        r = self.csv(self.HEADER + "Pâine albă;30;4,50\r\nBrânză de vaci 250 g;12;9,99\r\nApă plată 2 L;48;3,49\r\n")
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual({k: r.get_json()[k] for k in ("created", "updated", "ignored_columns", "auto_codes")},
                         {"created": 3, "updated": 0, "ignored_columns": [],
                          "auto_codes": {"count": 3, "first": "1", "last": "3"}})
        self.assertEqual([(p["code"], p["name"], p["price_bani"], p["stock_qty"]) for p in self.all_products()], [
            ("3", "Apă plată 2 L", 349, 48), ("2", "Brânză de vaci 250 g", 999, 12), ("1", "Pâine albă", 450, 30),
        ])

    def test_same_list_again_updates_prices_by_name(self):
        self.csv(self.HEADER + "Pâine albă;30;4,50\r\nApă plată 2 L;48;3,49\r\n")
        r = self.csv(self.HEADER + "PAINE ALBA;25;4,75\r\nApă plată 2 L;48;3,49\r\nCovrigi;50;1,50\r\n")
        body = r.get_json()
        self.assertEqual((body["created"], body["updated"], body["unchanged"], body["stock_ignored"]), (1, 1, 1, 1))
        self.assertEqual(body["auto_codes"], {"count": 1, "first": "3", "last": "3"})
        bread = self.product("1")
        self.assertEqual((bread["price_bani"], bread["stock_qty"]), (475, 30))  # stocul: doar prin mișcări
        self.assertEqual(len(self.all_products()), 3)

    def test_utf8_csv_with_commas_and_the_same_headers_in_xlsx(self):
        r = self.csv('\ufeffDenumire Produs,Cantitate Produs,Pret Vanzare\n"Lapte 1,5% 1 L",24,"7,99"\n', "utf-8")
        self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.product("1")["price_bani"], 799)
        self.imported(["Denumire Produs", "Cantitate Produs", "Pret Vanzare"], ["Iaurt", 12, 11.5])
        self.assertEqual((self.product("2")["name"], self.product("2")["price_bani"]), ("Iaurt", 1150))

    def test_new_codes_follow_the_biggest_numeric_code(self):
        self.create(code="7", name="Șapte")
        self.create(code="A12", name="Cu litere")
        self.csv(self.HEADER + "Unu;1;1\r\nDoi;1;2\r\n")
        self.assertEqual((self.product("8")["name"], self.product("9")["name"]), ("Unu", "Doi"))

    def test_names_must_be_unambiguous_without_codes(self):
        self.create(code="10", name="Covrigi")
        self.create(code="11", name="covrigi")
        r = self.csv(self.HEADER + "Mere;1;2\r\nMere;1;3\r\nCovrigi;1;1,5\r\nPere;2,5;6\r\n")
        self.assertError(r, 400, "Fișierul are 3 erori")
        self.assertEqual([(e["row"], e["message"]) for e in r.get_json()["errors"]], [
            (3, "Denumirea „Mere” apare și pe rândul 2"),
            (4, "Există 2 produse „Covrigi” — adăugați o coloană Cod, ca să se știe care"),
            (5, "Stoc: „2,5” nu este un număr întreg pozitiv"),
        ])

    def test_prices_with_thousands_separators(self):
        self.csv(self.HEADER + "Televizor;1;1.234,50\r\nFrigider;1;\"2,345.60\"\r\n")
        self.assertEqual((self.product("1")["price_bani"], self.product("2")["price_bani"]), (123450, 234560))


class ExportSalesTest(SalesTestCase):
    def test_receipts_and_lines(self):
        r = self.client.get("/api/excel/sales")
        self.assertEqual(r.status_code, 200)
        receipts, lines = sheet_rows(r.data, 0), sheet_rows(r.data, 1)
        self.assertEqual([row[0] for row in receipts[1:]], [self.cash_order, self.card_order])
        self.assertEqual([row[4:7] for row in receipts[1:]], [["numerar", 20.24, 50], ["card", 16.6, None]])
        self.assertEqual(lines[0][3:11], ["Produs", "Cantitate", "UM", "Preț (lei)", "Preț catalog (lei)",
                                          "Preț modificat (lei)", "Reducere (%)", "Total (lei)"])
        self.assertEqual([(row[3], row[4], row[5], row[8], row[10]) for row in lines[1:]], [
            ("Roșii", 1.25, "kg", None, 11.24),
            ("Pâine", 2, "buc", None, 9),
            ("Lapte", 1, "buc", None, 12.1),
            ("Pâine", 1, "buc", None, 4.5),
        ])

    def test_line_with_a_new_price_and_a_discount(self):
        product_a = self.create(code="500", name="Produs A", price_bani=12000)
        oid = self.order((product_a, 1000))
        line = self.get(oid)["items"][0]["id"]
        self.client.patch(f"/api/orders/{oid}/items/{line}", json={"manual_price_bani": 10000, "discount_bp": 3000})
        self.pay(oid, payment_method="card")
        lines = sheet_rows(self.client.get("/api/excel/sales").data, 1)
        row = next(r for r in lines[1:] if r[3] == "Produs A")
        self.assertEqual(row[6:11], [70, 120, 100, 30, 70])  # încasat, catalog, preț nou, reducere %, total


if __name__ == "__main__":
    unittest.main()
