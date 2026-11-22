import csv
import io
import sqlite3
from decimal import Decimal, InvalidOperation

from flask import Blueprint, jsonify, request, send_file
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from database import KG_PRODUCT_CODE, request_db
from errors import ApiError
from routes.products import MAX_PRICE_BANI, MAX_QTY
from routes.reports import PAID_IN_PERIOD, period_params, sales_period
from search import search_key

excel_bp = Blueprint("excel", __name__, url_prefix="/api/excel")

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_ROWS = 20_000
MAX_ROW_ERRORS = 200   # câte erori se întorc; restul doar se numără

# Coloanele catalogului (doar produse la bucată — vânzarea la kilogram are un
# singur preț, setat în aplicație): exportul și importul folosesc aceleași capete
# de tabel, deci un fișier exportat, modificat în Excel și reimportat merge direct.
# La import se acceptă și denumirile uzuale din alte programe (liste de gestiune).
# (cheie, capul de tabel la export, alte denumiri acceptate la import)
COLUMNS = [
    ("code", "Cod", ("cod produs", "plu")),
    ("barcode", "Cod de bare", ("ean", "barcode")),
    ("name", "Denumire", ("nume", "produs", "denumire produs", "nume produs")),
    ("price", "Preț (lei)", ("pret", "pret lei", "pret (lei / buc)", "pret vanzare", "pret de vanzare",
                             "pret vanzare (lei)", "pret cu tva")),
    ("stock", "Stoc (buc)", ("stoc", "cantitate", "cantitate produs")),
    ("min_stock", "Stoc minim", ()),
    ("active", "Activ", ()),
]
# Recunoscută doar la import: o listă cu produse la kg nu trebuie să le
# transforme pe tăcute în produse la bucată
_UNIT_COLUMN = ("sale_type", "Categorie", ("vanzare (kg/buc)", "categorie (buc/kg)", "vanzare", "tip", "um"))
REQUIRED = ("name", "price")  # fără Cod: coduri date automat, potrivire după denumire
_HEADER_KEYS = {search_key(alias): key for key, label, aliases in (*COLUMNS, _UNIT_COLUMN)
                for alias in (label, *aliases)}
_LABELS = {key: label for key, label, _ in COLUMNS}

_PER_PIECE = {"", "buc", "bucata", "bucati", "unit", "la bucata"}
_PER_KG = {"kg", "weight", "greutate", "kilogram", "la kg", "la kilogram"}
_YES = {"", "da", "1", "true", "activ", "x"}
_NO = {"nu", "0", "false", "inactiv"}


class RowError(Exception):
    pass


# ─── Celule ───────────────────────────────────────────────────────────────────

def _cell_text(value):
    """Celula ca text. Excel ține codurile numerice ca numere: 101.0 → "101"."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "da" if value else "nu"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _code(value, label, max_len, required):
    text = _cell_text(value)
    if isinstance(value, float) and not value.is_integer():
        raise RowError(f"{label}: „{value}” nu este un cod")
    if not text and required:
        raise RowError(f"{label} lipsește")
    if len(text) > max_len:
        raise RowError(f"{label}: cel mult {max_len} caractere")
    return text


def _money(value):
    """
    Preț în lei („12,50”, 12.5, „1.234,50”) → bani. Zgomotul de float din formule
    (0,30000000000000004) e tolerat. Cu punct și virgulă, ultimul e zecimala.
    """
    text = _cell_text(value)
    if "," in text and "." in text:
        text = text.replace(".", "") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    text = text.replace(",", ".")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise RowError(f"Preț: „{_cell_text(value)}” nu este un număr") from None
    rounded = amount.quantize(Decimal("0.01")) if amount.is_finite() else amount
    if not amount.is_finite() or abs(amount - rounded) > Decimal("0.000001"):
        raise RowError(f"Preț: „{_cell_text(value)}” are mai mult de două zecimale")
    bani = int(rounded * 100)
    if not 0 <= bani <= MAX_PRICE_BANI:
        raise RowError(f"Preț: trebuie să fie între 0 și {MAX_PRICE_BANI // 100} lei")
    return bani


def _count(value, label, allow_negative=False):
    text = _cell_text(value)
    if not text:
        return 0
    digits = text[1:] if allow_negative and text.startswith("-") else text
    if not digits.isdigit():
        raise RowError(f"{label}: „{text}” nu este un număr întreg" + ("" if allow_negative else " pozitiv"))
    if int(digits) > MAX_QTY:
        raise RowError(f"{label}: cel mult {MAX_QTY}")
    return int(text)


# ─── Import ───────────────────────────────────────────────────────────────────

def _read_header(header):
    columns, ignored = {}, []
    for index, cell in enumerate(header or ()):
        text = _cell_text(cell)
        if not text:
            continue
        key = _HEADER_KEYS.get(search_key(text))
        if key is None or key in columns:
            ignored.append(text)
        else:
            columns[key] = index
    missing = [_LABELS[k] for k in REQUIRED if k not in columns]
    if missing:
        raise ApiError("Lipsesc coloanele: " + ", ".join(missing) + " — primul rând trebuie să conțină capetele de tabel")
    return columns, ignored


class _Catalog:
    """Ce e deja în baza de date, încărcat o dată pentru tot fișierul."""

    def __init__(self, db):
        self.products = {p["code"]: dict(p) for p in db.execute(
            "SELECT id, code, barcode, name, price_bani, stock_qty, min_stock_qty, active FROM products "
            "WHERE sale_type = 'unit'")}
        self.barcode_owner = {p["barcode"]: code for code, p in self.products.items() if p["barcode"]}
        # Pentru fișierele fără coloana Cod: produsul existent se găsește după denumire
        self.codes_by_name = {}
        for code, p in self.products.items():
            self.codes_by_name.setdefault(search_key(p["name"]), []).append(code)
        self.all_codes = {r[0] for r in db.execute("SELECT code FROM products")}


def _free_codes(used):
    """Coduri noi, 1, 2, 3…, după cel mai mare cod numeric existent."""
    number = max((int(c) for c in used if c.isdigit()), default=0)
    while True:
        number += 1
        if str(number) not in used:
            yield str(number)


def _csv_rows(data):
    """
    Rândurile unui .csv. Excel în română salvează cu „;” (virgula e zecimală) și,
    la „CSV” simplu, în codarea Windows (cp1250); „CSV UTF-8” are BOM.
    """
    for encoding in ("utf-8-sig", "cp1250"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ApiError("Fișierul CSV nu se poate citi — salvați-l din Excel ca „CSV UTF-8”")
    first_line = text.split("\n", 1)[0]
    delimiter = max(";,\t", key=first_line.count)
    try:
        return list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))
    except csv.Error as exc:
        raise ApiError(f"Fișierul CSV nu se poate citi ({exc})") from None


def _parse_row(values, columns, catalog):
    def cell(key):
        index = columns.get(key)
        return values[index] if index is not None and index < len(values) else None

    item = {"code": _code(cell("code"), "Cod", 32, required=True) if "code" in columns else None}
    if item["code"] == KG_PRODUCT_CODE:
        raise RowError(f"Codul „{KG_PRODUCT_CODE}” e rezervat pentru vânzarea la kilogram")
    if "barcode" in columns:
        item["barcode"] = _code(cell("barcode"), "Cod de bare", 64, required=False) or None
    name = " ".join(_cell_text(cell("name")).split())
    if not name:
        raise RowError("Denumirea lipsește")
    if len(name) > 200:
        raise RowError("Denumire: cel mult 200 de caractere")
    item["name"] = name
    if "code" not in columns:
        matches = catalog.codes_by_name.get(search_key(name), [])
        if len(matches) > 1:
            raise RowError(f"Există {len(matches)} produse „{name}” — adăugați o coloană Cod, ca să se știe care")
        item["code"] = matches[0] if matches else None  # None = produs nou: primește un cod la scriere
    unit = search_key(_cell_text(cell("sale_type")))
    if unit in _PER_KG:
        raise RowError(f"Categorie: „{_cell_text(cell('sale_type'))}” — produsele la kg nu se importă: "
                       "la kilogram e un singur preț, setat în Produse → La kilogram")
    if unit not in _PER_PIECE:
        raise RowError(f"Categorie: „{_cell_text(cell('sale_type'))}” — aici sunt doar produse la bucată (buc)")
    item["price_bani"] = _money(cell("price"))
    if "stock" in columns:
        # Stocul exportat poate fi negativ (vândut înainte de recepție). El contează
        # doar la produsele noi, deci la cele existente un minus nu e o greșeală.
        item["stock"] = _count(cell("stock"), "Stoc", allow_negative=item["code"] in catalog.products)
    if "min_stock" in columns:
        item["min_stock_qty"] = _count(cell("min_stock"), "Stoc minim")
    if "active" in columns:
        active = search_key(_cell_text(cell("active")))
        if active not in _YES | _NO:
            raise RowError(f"Activ: „{_cell_text(cell('active'))}” — scrieți da sau nu")
        item["active"] = int(active in _YES)
    return item


@excel_bp.post("/products")
def import_products():
    """
    Catalogul din .xlsx (prima foaie) sau .csv; primul rând = capetele de tabel,
    în orice ordine. Obligatorii: denumirea și prețul. Produsele se potrivesc după
    cod: cele noi se creează, cele existente se actualizează, cele care lipsesc din
    fișier rămân neatinse. Fără coloana Cod, potrivirea se face după denumire, iar
    produsele noi primesc coduri 1, 2, 3… (după cel mai mare cod numeric existent).
      - doar produse la bucată: un rând marcat „kg” e o eroare (vânzarea la
        kilogram are un singur preț, setat în aplicație)
      - TVA-ul e fix (21%): o coloană TVA din fișier se ignoră
      - o coloană prezentă se aplică exact, inclusiv celulele goale (cod de bare
        gol = fără cod de bare); o coloană care lipsește nu se atinge
      - „Stoc (buc)” contează doar la produsele noi: stocul celor existente se
        schimbă numai prin mișcări de stoc, ca registrul să rămână complet
    Totul sau nimic: la orice eroare nu se scrie nimic, iar răspunsul listează
    rândurile greșite în "errors".
    """
    upload = request.files.get("file")
    if upload is None:
        raise ApiError("Trimiteți fișierul Excel în câmpul 'file'")
    if (upload.filename or "").lower().endswith(".csv"):
        rows = iter(_csv_rows(upload.read()))
        header = next(rows, None)
    else:
        try:
            workbook = load_workbook(io.BytesIO(upload.read()), read_only=True, data_only=True)
            rows = workbook.worksheets[0].iter_rows(values_only=True)
            header = next(rows, None)
        except Exception:
            # Fișier încărcat de utilizator: orice nu se poate citi e „nu e .xlsx”
            raise ApiError("Fișierul nu este un document Excel .xlsx valid (sau un .csv)") from None
    columns, ignored = _read_header(header)

    db = request_db()
    catalog = _Catalog(db)
    parsed, errors, error_count = [], [], 0
    rows_by_code, rows_by_name, rows_by_barcode = {}, {}, {}
    for number, values in enumerate(rows, start=2):
        if not values or all(_cell_text(v) == "" for v in values):
            continue
        if len(parsed) + error_count >= MAX_ROWS:
            raise ApiError(f"Fișierul are mai mult de {MAX_ROWS} de produse")
        try:
            item = _parse_row(values, columns, catalog)
            name_key = search_key(item["name"])
            if "code" not in columns and name_key in rows_by_name:
                raise RowError(f"Denumirea „{item['name']}” apare și pe rândul {rows_by_name[name_key]}")
            if item["code"] is not None and item["code"] in rows_by_code:
                raise RowError(f"Codul „{item['code']}” apare și pe rândul {rows_by_code[item['code']]}")
            barcode = item.get("barcode")
            if barcode and barcode in rows_by_barcode:
                raise RowError(f"Codul de bare „{barcode}” apare și pe rândul {rows_by_barcode[barcode]}")
        except RowError as exc:
            error_count += 1
            if len(errors) < MAX_ROW_ERRORS:
                errors.append({"row": number, "message": str(exc)})
            continue
        if item["code"] is not None:
            rows_by_code[item["code"]] = number
        rows_by_name[name_key] = number
        if barcode:
            rows_by_barcode[barcode] = number
        parsed.append((number, item))

    # Cod de bare al unui produs existent care nu e în fișier (și deci nu și-l schimbă)
    for number, item in parsed:
        owner = catalog.barcode_owner.get(item.get("barcode"))
        if owner and owner != item["code"] and owner not in rows_by_code:
            error_count += 1
            if len(errors) < MAX_ROW_ERRORS:
                errors.append({"row": number, "message": f"Codul de bare „{item['barcode']}” e deja al produsului {owner}"})
    if error_count:
        errors.sort(key=lambda e: e["row"])
        word = "eroare" if error_count == 1 else "erori"
        raise ApiError(f"Fișierul are {error_count} {word} — nu s-a importat nimic", 400,
                       {"errors": errors, "error_count": error_count})
    if not parsed:
        raise ApiError("Fișierul nu conține niciun produs")

    created = updated = unchanged = stock_ignored = 0
    free_codes, auto_codes = _free_codes(catalog.all_codes), []
    try:
        for _, item in parsed:
            stock = item.pop("stock", None)
            item["search_name"] = search_key(item["name"])
            existing = catalog.products.get(item["code"])
            if existing is None:
                if item["code"] is None:
                    item["code"] = next(free_codes)
                    auto_codes.append(item["code"])
                row = {**item, "sale_type": "unit"}
                cur = db.execute(f"INSERT INTO products ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                                 tuple(row.values()))
                if stock:
                    db.execute("INSERT INTO stock_movements (product_id, delta_qty, reason, note) "
                               "VALUES (?, ?, 'receipt', 'Stoc inițial (import Excel)')", (cur.lastrowid, stock))
                created += 1
                continue
            if stock is not None and stock != existing["stock_qty"]:
                stock_ignored += 1
            changes = {k: v for k, v in item.items() if k != "search_name" and existing.get(k) != v}
            if not changes:
                unchanged += 1
                continue
            if "name" in changes:
                changes["search_name"] = item["search_name"]
            sets = ", ".join(f"{col} = ?" for col in changes)
            db.execute(f"UPDATE products SET {sets}, updated_at = datetime('now','localtime') WHERE id = ?",
                       (*changes.values(), existing["id"]))
            updated += 1
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        raise ApiError("Importul contrazice datele existente (cod sau cod de bare duplicat) — nu s-a importat nimic", 409) from None

    return jsonify({
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "stock_ignored": stock_ignored,
        "ignored_columns": ignored,
        # fără coloana Cod: codurile date produselor noi (le tastează casierul)
        "auto_codes": {"count": len(auto_codes), "first": auto_codes[0], "last": auto_codes[-1]} if auto_codes else None,
    })


# ─── Export ───────────────────────────────────────────────────────────────────

def _sheet(workbook, title, headers, widths, first=False):
    ws = workbook.active if first else workbook.create_sheet()
    ws.title = title
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    ws.freeze_panes = "A2"
    for letter, width in zip("ABCDEFGHIJKLMNOP", widths):
        ws.column_dimensions[letter].width = width
    return ws


def _format(ws, columns, number_format):
    for column in columns:
        for cell in ws[column][1:]:
            cell.number_format = number_format


def _download(workbook, filename):
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return send_file(buffer, mimetype=XLSX, as_attachment=True, download_name=filename)


def _lei(bani):
    return None if bani is None else Decimal(bani) / 100


@excel_bp.get("/products")
def export_products():
    """Tot catalogul (produsele la bucată), în formatul acceptat de import (gol = șablon de completat)."""
    rows = request_db().execute(
        """
        SELECT p.code, p.barcode, p.name, p.price_bani, p.stock_qty, p.min_stock_qty, p.active
          FROM products p
         WHERE p.sale_type = 'unit'
         ORDER BY p.search_name, p.id
        """
    ).fetchall()
    workbook = Workbook()
    ws = _sheet(workbook, "Produse", [label for _, label, _ in COLUMNS], [10, 16, 40, 11, 11, 11, 7], first=True)
    for r in rows:
        ws.append([r["code"], r["barcode"] or "", r["name"], _lei(r["price_bani"]), r["stock_qty"],
                   r["min_stock_qty"], "da" if r["active"] else "nu"])
    _format(ws, "AB", "@")  # codurile rămân text: zerourile din față nu se pierd
    _format(ws, "D", "0.00")
    return _download(workbook, "produse.xlsx")


@excel_bp.get("/sales")
def export_sales():
    """Bonurile plătite din perioadă (date_from, date_to; implicit azi) — o foaie pe bonuri, una pe linii."""
    date_from, date_to = sales_period()
    params = period_params(date_from, date_to)
    db = request_db()
    workbook = Workbook()

    receipts = _sheet(workbook, "Bonuri", [
        "Comanda", "Data plății", "Bon fiscal", "Raport Z", "Plată", "Total (lei)", "Primit (lei)",
        "CUI client", "Client", "Simulat",
    ], [10, 20, 12, 10, 8, 12, 12, 14, 30, 8], first=True)
    for o in db.execute(
        f"""
        SELECT o.id, o.fiscalized_at, o.fiscal_receipt_number, o.fiscal_z_number, o.payment_method,
               o.total_bani, o.cash_received_bani, o.buyer_cui, o.buyer_name, o.fiscal_simulated
          FROM orders o
         WHERE {PAID_IN_PERIOD}
         ORDER BY o.fiscalized_at, o.id
        """,
        params,
    ):
        receipts.append([o["id"], o["fiscalized_at"], o["fiscal_receipt_number"], o["fiscal_z_number"],
                         "numerar" if o["payment_method"] == "cash" else "card", _lei(o["total_bani"]),
                         _lei(o["cash_received_bani"]), o["buyer_cui"], o["buyer_name"],
                         "da" if o["fiscal_simulated"] else "nu"])
    _format(receipts, "FG", "#,##0.00")

    lines = _sheet(workbook, "Linii", [
        "Comanda", "Data plății", "Cod", "Produs", "Cantitate", "UM", "Preț (lei)",
        "Preț catalog (lei)", "Preț modificat (lei)", "Reducere (%)", "Total (lei)", "TVA", "Cota (%)",
    ], [10, 20, 10, 36, 11, 6, 11, 16, 18, 12, 12, 6, 9])
    for i in db.execute(
        f"""
        SELECT o.id, o.fiscalized_at, p.code, i.product_name, i.sale_type,
               i.quantity_milli, i.unit_price_bani, i.list_price_bani, i.manual_price_bani, i.discount_bp,
               i.line_total_bani, i.vat_fiscal_code, i.vat_percent
          FROM order_items i
          JOIN orders o ON o.id = i.order_id
          JOIN products p ON p.id = i.product_id
         WHERE {PAID_IN_PERIOD}
         ORDER BY o.fiscalized_at, o.id, i.id
        """,
        params,
    ):
        lines.append([i["id"], i["fiscalized_at"], i["code"], i["product_name"],
                      Decimal(i["quantity_milli"]) / 1000, "kg" if i["sale_type"] == "weight" else "buc",
                      _lei(i["unit_price_bani"]), _lei(i["list_price_bani"]), _lei(i["manual_price_bani"]),
                      Decimal(i["discount_bp"]) / 100, _lei(i["line_total_bani"]),
                      i["vat_fiscal_code"], i["vat_percent"]])
    _format(lines, "C", "@")
    _format(lines, "E", "0.000")
    _format(lines, "GHIK", "#,##0.00")
    _format(lines, "J", "0.00")

    period = date_from.isoformat() if date_from == date_to else f"{date_from.isoformat()}_{date_to.isoformat()}"
    return _download(workbook, f"vanzari-{period}.xlsx")
