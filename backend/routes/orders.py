import logging
import threading
from datetime import timedelta

from flask import Blueprint, jsonify, request

import fiscal
from database import request_db
from errors import ApiError
from routes.products import MAX_PRICE_BANI
from search import like_escape
from validation import MISSING, choice, cui, integer, query_date, query_int, read_json, text

log = logging.getLogger(__name__)

orders_bp = Blueprint("orders", __name__, url_prefix="/api/orders")

STATUSES = ("pending", "paid", "cancelled")
BUYER_TYPES = ("pf", "pj")
PAYMENT_METHODS = ("cash", "card")
MAX_CASH_BANI = 99_999_999
MAX_QUANTITY_MILLI = 10_000_000   # 10.000 kg sau bucăți pe o linie — oprește greșelile de tastare
MAX_DISCOUNT_BP = 9_999           # reducerea, în sutimi de procent: cel mult 99,99%

# Toate modificările comenzilor trec pe rând (un singur proces, o singură casă
# de marcat). Plata ține lock-ul cât tipărește casa, așa că:
#   - un dublu-click pe „Plătește” nu tipărește două bonuri: a doua cerere
#     așteaptă și găsește apoi comanda deja plătită;
#   - liniile nu se pot schimba între bonul tipărit și ce se salvează.
orders_lock = threading.Lock()

_ORDER_FIELDS = {"customer_id", "buyer_type", "buyer_name", "buyer_cui", "notes"}
_BUYER_FIELDS = {"buyer_type", "buyer_name", "buyer_cui"}

_ORDER_SELECT = """
    SELECT o.id, o.status, o.buyer_type, o.customer_id, o.buyer_name, o.buyer_cui, o.total_bani,
           o.payment_method, o.cash_received_bani, o.fiscal_receipt_number, o.fiscal_z_number,
           o.fiscalized_at, o.fiscal_simulated, o.notes, o.created_at, o.updated_at,
           (SELECT COUNT(*) FROM order_items i WHERE i.order_id = o.id) AS item_count
      FROM orders o
"""

_ITEM_SELECT = """
    SELECT id, product_id, product_name, sale_type, quantity_milli, list_price_bani, manual_price_bani,
           discount_bp, unit_price_bani, price_overridden, vat_fiscal_code, vat_percent, line_total_bani
      FROM order_items
"""

_PRODUCT_FOR_SALE = "SELECT name, sale_type, price_bani, active FROM products WHERE id = ?"


def line_total_bani(quantity_milli, unit_price_bani):
    """Totalul liniei, rotunjit comercial (de la 0,5 bani în sus), fără float."""
    return (quantity_milli * unit_price_bani + 500) // 1000


def discounted_price(list_price_bani, discount_bp):
    """
    Prețul unitar după reducere (sutimi de procent), rotunjit comercial: 6,99 lei
    cu 10% → 6,29. Casa primește acest preț, deci totalul de pe bon iese identic.
    """
    return (list_price_bani * (10_000 - discount_bp) + 5_000) // 10_000


def _to_dict(row):
    order = dict(row)
    order["fiscal_simulated"] = bool(order["fiscal_simulated"])
    return order


def _get_order(db, order_id):
    row = db.execute(_ORDER_SELECT + " WHERE o.id = ?", (order_id,)).fetchone()
    if row is None:
        raise ApiError("Comanda nu există", 404)
    order = _to_dict(row)
    items = db.execute(_ITEM_SELECT + " WHERE order_id = ? ORDER BY id", (order_id,)).fetchall()
    # price_overridden: linia nu e la prețul din catalog — preț nou, reducere sau
    # amândouă (și când, întâmplător, rezultatul e chiar prețul din catalog)
    order["items"] = [
        {**dict(r), "price_overridden": bool(r["price_overridden"] or r["manual_price_bani"] is not None
                                             or r["discount_bp"])}
        for r in items
    ]
    return order


def _get_pending_order(db, order_id):
    """Comanda, cât timp se mai poate modifica; plătită sau anulată → 409."""
    order = _get_order(db, order_id)
    if order["status"] == "paid":
        raise ApiError("Comanda este deja plătită", 409)
    if order["status"] == "cancelled":
        raise ApiError("Comanda este anulată", 409)
    return order


def _get_item(order, item_id):
    for item in order["items"]:
        if item["id"] == item_id:
            return item
    raise ApiError("Linia nu există pe această comandă", 404)


def _check_quantity(sale_type, quantity_milli):
    if sale_type == "unit" and quantity_milli % 1000:
        raise ApiError("Produsele la bucată se vând doar în bucăți întregi (quantity_milli multiplu de 1000)")
    if quantity_milli > MAX_QUANTITY_MILLI:
        raise ApiError(f"Cantitatea pe o linie poate fi cel mult {MAX_QUANTITY_MILLI}")


def _refresh_total(db, order_id):
    db.execute(
        """
        UPDATE orders
           SET total_bani = (SELECT COALESCE(SUM(line_total_bani), 0) FROM order_items WHERE order_id = ?),
               updated_at = datetime('now','localtime')
         WHERE id = ?
        """,
        (order_id, order_id),
    )


def _read_order_fields(db, data):
    """
    Coloanele de scris din cerere. Cumpărătorul se trimite întreg, într-unul
    din două feluri:
      customer_id                         client salvat — datele lui se copiază
                                          (și din nou la plată); null → fără client
      buyer_type, buyer_name, buyer_cui   tastat la casă; buyer_cui obligatoriu
                                          și verificat la persoană juridică (pj)
    """
    fields = {}
    notes = text(data, "notes", 500, nullable=True)
    if notes is not MISSING:
        fields["notes"] = notes or ""

    if "customer_id" in data:
        if _BUYER_FIELDS & data.keys():
            raise ApiError("Trimiteți fie 'customer_id', fie datele cumpărătorului — nu ambele")
        customer_id = integer(data, "customer_id", nullable=True)
        if customer_id is None:
            fields.update(customer_id=None, buyer_type="pf", buyer_name="", buyer_cui="")
        else:
            c = db.execute("SELECT type, name, cui FROM customers WHERE id = ?", (customer_id,)).fetchone()
            if c is None:
                raise ApiError("Clientul nu există")
            fields.update(customer_id=customer_id, buyer_type=c["type"], buyer_name=c["name"], buyer_cui=c["cui"] or "")
    elif _BUYER_FIELDS & data.keys():
        buyer_type = choice(data, "buyer_type", BUYER_TYPES, required=True)
        buyer_name = text(data, "buyer_name", 200, nullable=True)
        buyer_cui = cui(data, "buyer_cui")
        has_cui = isinstance(buyer_cui, str)
        if buyer_type == "pj" and not has_cui:
            raise ApiError("Pentru persoană juridică, 'buyer_cui' este obligatoriu")
        if buyer_type == "pf" and has_cui:
            raise ApiError("Câmpul 'buyer_cui' se completează doar pentru persoană juridică")
        fields.update(
            customer_id=None,
            buyer_type=buyer_type,
            buyer_name=buyer_name if isinstance(buyer_name, str) else "",
            buyer_cui=buyer_cui if has_cui else "",
        )
    return fields


def _buyer(db, order):
    """(tip, nume, CUI) de pus pe bon — copiate din clientul salvat, dacă există."""
    if order["customer_id"] is not None:
        c = db.execute("SELECT type, name, cui FROM customers WHERE id = ?", (order["customer_id"],)).fetchone()
        if c is not None:
            return c["type"], c["name"], c["cui"] or ""
    return order["buyer_type"], order["buyer_name"], order["buyer_cui"]


# ─── Comenzi ──────────────────────────────────────────────────────────────────

@orders_bp.get("/")
def list_orders():
    """
    Comenzile, cele mai noi primele, fără linii (item_count spune câte are).
      status             pending | paid | cancelled, sau mai multe: paid,cancelled — implicit toate
      date_from, date_to AAAA-LL-ZZ, incluse — ziua plății, sau a creării pentru cele neplătite
      q                  numărul bonului fiscal sau al comenzii (exact), ori o parte din CUI
      limit, offset      paginare (implicit 50, maxim 500)
    """
    where, params = [], []
    statuses = [s for s in request.args.get("status", "").split(",") if s]
    if statuses:
        if not set(statuses) <= set(STATUSES):
            raise ApiError("Parametrul 'status' trebuie să fie pending, paid sau cancelled")
        where.append(f"o.status IN ({', '.join('?' * len(statuses))})")
        params += statuses

    day = "COALESCE(o.fiscalized_at, o.created_at)"
    date_from = query_date("date_from", None)
    date_to = query_date("date_to", None)
    if date_from and date_to and date_from > date_to:
        raise ApiError("Data de început este după data de sfârșit")
    if date_from:
        where.append(f"{day} >= ?")
        params.append(date_from.isoformat())
    if date_to:
        where.append(f"{day} < ?")
        params.append((date_to + timedelta(days=1)).isoformat())

    q = request.args.get("q", "").strip()
    if q:
        matches = ["o.fiscal_receipt_number = ?", "o.buyer_cui LIKE ? ESCAPE '\\'"]
        params += [q, f"%{like_escape(q.upper())}%"]
        if q.isdigit() and len(q) <= 18:
            matches.append("o.id = ?")
            params.append(int(q))
        where.append(f"({' OR '.join(matches)})")

    limit = query_int("limit", 50, min_value=1, max_value=500)
    offset = query_int("offset", 0, min_value=0)
    where_sql = " WHERE " + " AND ".join(where) if where else ""

    db = request_db()
    total = db.execute("SELECT COUNT(*) FROM orders o" + where_sql, params).fetchone()[0]
    rows = db.execute(f"{_ORDER_SELECT}{where_sql} ORDER BY o.id DESC LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
    return jsonify({"items": [_to_dict(r) for r in rows], "total": total, "limit": limit, "offset": offset})


@orders_bp.post("/")
def create_order():
    """Bon nou, gol, în starea pending. Acceptă opțional cumpărătorul și notes (vezi PATCH)."""
    data = read_json(_ORDER_FIELDS)
    db = request_db()
    fields = _read_order_fields(db, data)
    if fields:
        cur = db.execute(
            f"INSERT INTO orders ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
            tuple(fields.values()),
        )
    else:
        cur = db.execute("INSERT INTO orders DEFAULT VALUES")
    db.commit()
    return jsonify(_get_order(db, cur.lastrowid)), 201


@orders_bp.get("/<id:order_id>")
def get_order(order_id):
    return jsonify(_get_order(request_db(), order_id))


@orders_bp.patch("/<id:order_id>")
def update_order(order_id):
    """Cumpărătorul și notes; doar pe comenzi pending."""
    data = read_json(_ORDER_FIELDS)
    db = request_db()
    fields = _read_order_fields(db, data)
    if not fields:
        raise ApiError("Nimic de modificat")
    with orders_lock:
        _get_pending_order(db, order_id)
        sets = ", ".join(f"{col} = ?" for col in fields)
        db.execute(
            f"UPDATE orders SET {sets}, updated_at = datetime('now','localtime') WHERE id = ?",
            (*fields.values(), order_id),
        )
        db.commit()
        return jsonify(_get_order(db, order_id))


@orders_bp.post("/<id:order_id>/cancel")
def cancel_order(order_id):
    """Anulează o comandă neplătită. Stocul nu se atinge — scade doar la plată."""
    with orders_lock:
        db = request_db()
        _get_pending_order(db, order_id)
        db.execute(
            "UPDATE orders SET status = 'cancelled', updated_at = datetime('now','localtime') WHERE id = ?",
            (order_id,),
        )
        db.commit()
        return jsonify(_get_order(db, order_id))


# ─── Linii ────────────────────────────────────────────────────────────────────

@orders_bp.post("/<id:order_id>/items")
def add_item(order_id):
    """
    Adaugă un produs pe bon; numele, tipul și prețul se copiază din produs, iar
    TVA-ul e cota fixă a magazinului (fiscal.VAT_GROUP / VAT_PERCENT).
      product_id       obligatoriu
      quantity_milli   1 kg = 1000, 1 buc = 1000; obligatoriu la produsele la kg,
                       implicit 1 buc la cele la bucată
    Același produs, la același preț, fără preț nou și fără reducere, se adună pe
    linia existentă. Prețul nou și reducerea se dau apoi pe linie (PATCH .../items/<id>).
    Răspunsul e comanda întreagă, cu totalul actualizat.
    """
    data = read_json({"product_id", "quantity_milli"})
    product_id = integer(data, "product_id", required=True)
    quantity = integer(data, "quantity_milli", min_value=1, max_value=MAX_QUANTITY_MILLI)

    with orders_lock:
        db = request_db()
        order = _get_pending_order(db, order_id)
        product = db.execute(_PRODUCT_FOR_SALE, (product_id,)).fetchone()
        if product is None:
            raise ApiError("Produsul nu există")
        if not product["active"]:
            raise ApiError(f"Produsul „{product['name']}” nu este activ")
        if product["sale_type"] == "weight" and product["price_bani"] == 0:
            raise ApiError("Prețul pe kilogram nu e setat — setați-l în Produse → La kilogram")
        if quantity is MISSING:
            if product["sale_type"] == "weight":
                raise ApiError("Câmpul 'quantity_milli' este obligatoriu la produsele vândute la kg")
            quantity = 1000
        price = product["price_bani"]

        same = next(
            (i for i in order["items"] if i["product_id"] == product_id and i["discount_bp"] == 0
             and i["manual_price_bani"] is None and i["unit_price_bani"] == price),
            None,
        )
        if same is not None:
            quantity += same["quantity_milli"]
        _check_quantity(product["sale_type"], quantity)

        if same is not None:
            db.execute(
                "UPDATE order_items SET quantity_milli = ?, line_total_bani = ? WHERE id = ?",
                (quantity, line_total_bani(quantity, price), same["id"]),
            )
        else:
            db.execute(
                "INSERT INTO order_items (order_id, product_id, product_name, sale_type, quantity_milli, "
                "list_price_bani, unit_price_bani, vat_fiscal_code, vat_percent, line_total_bani) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (order_id, product_id, product["name"], product["sale_type"], quantity,
                 product["price_bani"], price, fiscal.VAT_GROUP, fiscal.VAT_PERCENT,
                 line_total_bani(quantity, price)),
            )
        _refresh_total(db, order_id)
        db.commit()
        return jsonify(_get_order(db, order_id)), 201


@orders_bp.patch("/<id:order_id>/items/<id:item_id>")
def update_item(order_id, item_id):
    """
    Cantitatea și/sau prețul unei linii. Prețul are două părți, care se combină:
      manual_price_bani  prețul nou pe bucată / kg („Modificare preț”), în locul celui
                         din catalog; null = înapoi la prețul din catalog
      discount_bp        reducerea în sutimi de procent (10% = 1000, 12,5% = 1250),
                         0 = fără reducere; se aplică prețului nou, dacă linia are
                         unul, altfel celui din catalog
    Prețul încasat = (prețul nou sau cel din catalog) minus reducerea; ce nu se
    trimite rămâne cum era. Ex.: 120 lei → preț nou 100 → apoi 30% → 70 lei; cu
    reducerea schimbată la 20% → 80 (tot din 100, nu din 70).
    """
    data = read_json({"quantity_milli", "discount_bp", "manual_price_bani"})
    quantity = integer(data, "quantity_milli", min_value=1, max_value=MAX_QUANTITY_MILLI)
    discount = integer(data, "discount_bp", min_value=0, max_value=MAX_DISCOUNT_BP)
    manual = integer(data, "manual_price_bani", nullable=True, min_value=1, max_value=MAX_PRICE_BANI)
    if quantity is MISSING and discount is MISSING and manual is MISSING:
        raise ApiError("Nimic de modificat")

    with orders_lock:
        db = request_db()
        item = _get_item(_get_pending_order(db, order_id), item_id)
        if quantity is MISSING:
            quantity = item["quantity_milli"]
        if discount is MISSING and manual is MISSING:
            # doar cantitatea: prețul rămâne exact cum e
            price, discount, manual = item["unit_price_bani"], item["discount_bp"], item["manual_price_bani"]
        else:
            if discount is MISSING:
                discount = item["discount_bp"]
            if manual is MISSING:
                manual = item["manual_price_bani"]
            base = item["list_price_bani"] if manual is None else manual
            price = discounted_price(base, discount)
            if price == 0 and base > 0:
                raise ApiError("Reducerea e prea mare: prețul ar ajunge la 0 lei")
        _check_quantity(item["sale_type"], quantity)
        db.execute(
            "UPDATE order_items SET quantity_milli = ?, manual_price_bani = ?, discount_bp = ?, unit_price_bani = ?, "
            "line_total_bani = ? WHERE id = ?",
            (quantity, manual, discount, price, line_total_bani(quantity, price), item_id),
        )
        _refresh_total(db, order_id)
        db.commit()
        return jsonify(_get_order(db, order_id))


@orders_bp.delete("/<id:order_id>/items/<id:item_id>")
def delete_item(order_id, item_id):
    with orders_lock:
        db = request_db()
        _get_item(_get_pending_order(db, order_id), item_id)
        db.execute("DELETE FROM order_items WHERE id = ?", (item_id,))
        _refresh_total(db, order_id)
        db.commit()
        return jsonify(_get_order(db, order_id))


# ─── Plată ────────────────────────────────────────────────────────────────────

@orders_bp.post("/<id:order_id>/pay")
def pay_order(order_id):
    """
    Încasează comanda și emite bonul fiscal.
      payment_method      cash | card
      cash_received_bani  doar la cash, opțional — suma primită de la client
                          (implicit suma exactă); restul se calculează din ea
    Comanda devine 'paid' doar dacă casa a emis bonul; altfel rămâne
    'pending' și plata se poate reîncerca.
    """
    data = read_json({"payment_method", "cash_received_bani"})
    method = choice(data, "payment_method", PAYMENT_METHODS, required=True)
    cash = integer(data, "cash_received_bani", min_value=0, max_value=MAX_CASH_BANI)
    if method == "card" and cash is not MISSING:
        raise ApiError("Câmpul 'cash_received_bani' se trimite doar la plata cash")

    with orders_lock:
        db = request_db()
        order = _get_pending_order(db, order_id)
        if not order["items"]:
            raise ApiError("Comanda nu are produse")

        total = sum(i["line_total_bani"] for i in order["items"])
        if method == "cash":
            cash = total if cash is MISSING else cash
            if cash < total:
                raise ApiError("Suma primită este mai mică decât totalul bonului")
        else:
            cash = None
        buyer_type, buyer_name, buyer_cui = _buyer(db, order)

        receipt = fiscal.Receipt(
            order_id=order_id,
            lines=tuple(
                fiscal.SaleLine(
                    name=i["product_name"],
                    vat_fiscal_code=i["vat_fiscal_code"],
                    unit_price_bani=i["unit_price_bani"],
                    quantity_milli=i["quantity_milli"],
                    line_total_bani=i["line_total_bani"],
                    unit="kg" if i["sale_type"] == "weight" else "buc",
                )
                for i in order["items"]
            ),
            total_bani=total,
            payment_method=method,
            cash_received_bani=cash,
            buyer_cui=buyer_cui,
            buyer_name=buyer_name,
        )
        try:
            result = fiscal.send_receipt(receipt)
        except fiscal.FiscalError as exc:
            raise ApiError(str(exc), 503) from None
        if not result.ok:
            raise ApiError(result.message, 502)  # mesajul adaptorului e deja pentru casier

        # De aici bonul există pe casă — o eroare la salvare trebuie să se vadă în log
        try:
            db.execute(
                """
                UPDATE orders
                   SET status = 'paid', payment_method = ?, cash_received_bani = ?, total_bani = ?,
                       buyer_type = ?, buyer_name = ?, buyer_cui = ?,
                       fiscal_receipt_number = ?, fiscal_simulated = ?,
                       fiscalized_at = datetime('now','localtime'),
                       updated_at = datetime('now','localtime')
                 WHERE id = ?
                """,
                (method, cash, total, buyer_type, buyer_name, buyer_cui,
                 result.receipt_number, int(result.simulated), order_id),
            )
            # Doar produsele la bucată scad stocul la vânzare (vezi tabela products)
            db.execute(
                """
                INSERT INTO stock_movements (product_id, delta_qty, reason, order_id)
                SELECT product_id, -(SUM(quantity_milli) / 1000), 'sale', ?
                  FROM order_items
                 WHERE order_id = ? AND sale_type = 'unit'
                 GROUP BY product_id
                """,
                (order_id, order_id),
            )
            db.commit()
        except Exception:
            log.critical(
                "Bonul %s a fost emis pentru comanda %d, dar plata NU s-a salvat",
                result.receipt_number, order_id,
            )
            raise

        return jsonify({
            "order": _get_order(db, order_id),
            "change_bani": None if cash is None else cash - total,
            "fiscal_message": result.message,
        })
