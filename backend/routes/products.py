import sqlite3

from flask import Blueprint, jsonify, request

from database import KG_PRODUCT_CODE, request_db
from errors import ApiError
from search import like_escape, search_key
from validation import MISSING, boolean, choice, integer, query_int, read_json, text

products_bp = Blueprint("products", __name__, url_prefix="/api/products")

# Cele două categorii, fixe, după felul vânzării (database.py, products):
# produsele din catalog sunt toate la bucată; „la kilogram” e un singur rând,
# cu un preț pe kg pentru orice marfă (GET/PATCH /api/products/kg)
CATEGORY_NAMES = {"unit": "La bucată", "weight": "La kilogram"}
MAX_PRICE_BANI = 99_999_999   # 999.999,99 lei — peste orice preț real; oprește greșelile de tastare
MAX_QTY = 1_000_000           # idem pentru cantitățile de stoc
# Mișcări de stoc introduse manual; 'sale', 'cancel' și 'return' vin doar din bonuri
MANUAL_STOCK_REASONS = ("receipt", "adjustment")

# Câmpuri modificabile prin POST/PATCH. Stocul NU e printre ele: se schimbă
# doar prin mișcări (POST /<id>/stock), ca registrul de stoc să rămână complet.
_EDITABLE = {"code", "barcode", "name", "price_bani", "min_stock_qty", "active"}
_STOCK_FIELDS = {"stock_qty", "initial_stock_qty"}

# Stoc sub pragul minim — aceeași regulă în răspuns și în filtrul ?low_stock=1
_LOW_STOCK_SQL = "p.min_stock_qty > 0 AND p.stock_qty <= p.min_stock_qty"

_SELECT = f"""
    SELECT p.id, p.code, p.barcode, p.name, p.sale_type, p.price_bani,
           p.stock_qty, p.min_stock_qty, ({_LOW_STOCK_SQL}) AS low_stock,
           p.active, p.created_at, p.updated_at
      FROM products p
"""

_MOVEMENT_SELECT = "SELECT id, product_id, delta_qty, reason, order_id, note, created_at FROM stock_movements"


def _to_dict(row):
    product = dict(row)
    product["active"] = bool(product["active"])
    product["low_stock"] = bool(product["low_stock"])
    return product


def _get_product(db, product_id):
    row = db.execute(_SELECT + " WHERE p.id = ?", (product_id,)).fetchone()
    if row is None:
        raise ApiError("Produsul nu există", 404)
    return _to_dict(row)


def _read_fields(data, creating):
    """Câmpurile editabile, validate; cele absente din cerere lipsesc din rezultat."""
    fields = {
        "code":          text(data, "code", 32, required=creating),
        "barcode":       text(data, "barcode", 64, nullable=True),
        "name":          text(data, "name", 200, required=creating),
        "price_bani":    integer(data, "price_bani", required=creating, min_value=0, max_value=MAX_PRICE_BANI),
        "min_stock_qty": integer(data, "min_stock_qty", min_value=0, max_value=MAX_QTY),
        "active":        boolean(data, "active"),
    }
    fields = {k: v for k, v in fields.items() if v is not MISSING}
    if "name" in fields:
        fields["search_name"] = search_key(fields["name"])
    if "active" in fields:
        fields["active"] = int(fields["active"])
    return fields


def _catalog_product(db, product_id):
    """Un produs din catalog; rândul fix „la kilogram” se schimbă doar prin /api/products/kg."""
    product = _get_product(db, product_id)
    if product["code"] == KG_PRODUCT_CODE:
        raise ApiError("Vânzarea la kilogram nu e un produs din catalog — denumirea și prețul pe kg "
                       "se schimbă din Produse → La kilogram")
    return product


def _kg_product(db):
    return _to_dict(db.execute(_SELECT + " WHERE p.code = ?", (KG_PRODUCT_CODE,)).fetchone())


def _execute_unique(db, sql, params, fields):
    try:
        return db.execute(sql, params)
    except sqlite3.IntegrityError as exc:
        if "products.code" in str(exc):
            raise ApiError(f"Există deja un produs cu codul „{fields['code']}”", 409) from None
        if "products.barcode" in str(exc):
            raise ApiError(f"Există deja un produs cu codul de bare „{fields['barcode']}”", 409) from None
        raise


@products_bp.get("/")
def list_products():
    """
    Catalogul: produsele la bucată (fără rândul „la kilogram”, care are rutele lui).
    Parametri, toți opționali:
      q              caută în cod (început), cod de bare (exact) și nume — fără
                     diacritice, toate cuvintele trebuie să apară
      active         1 (implicit) | 0 | all
      low_stock      1 → doar produsele sub stocul minim
      limit, offset  paginare (implicit 50, maxim 500)
    """
    where, params = ["p.sale_type = 'unit'"], []

    active = request.args.get("active", "1")
    if active not in ("0", "1", "all"):
        raise ApiError("Parametrul 'active' trebuie să fie 0, 1 sau all")
    if active != "all":
        where.append("p.active = ?")
        params.append(int(active))

    if request.args.get("low_stock") == "1":
        where.append(_LOW_STOCK_SQL)

    order_sql, order_params = "p.search_name, p.id", []
    q = request.args.get("q", "").strip()
    if q:
        code_prefix = like_escape(q) + "%"
        terms = search_key(q).split()
        name_sql = " AND ".join(["p.search_name LIKE ? ESCAPE '\\'"] * len(terms)) or "0"
        where.append(f"(p.code LIKE ? ESCAPE '\\' OR p.barcode = ? OR ({name_sql}))")
        params += [code_prefix, q] + [f"%{like_escape(t)}%" for t in terms]
        # Întâi potrivirea exactă pe cod / cod de bare, apoi începutul de cod, apoi numele
        order_sql = (
            "CASE WHEN p.code = ? OR p.barcode = ? THEN 0 "
            "WHEN p.code LIKE ? ESCAPE '\\' THEN 1 ELSE 2 END, " + order_sql
        )
        order_params = [q, q, code_prefix]

    limit = query_int("limit", 50, min_value=1, max_value=500)
    offset = query_int("offset", 0, min_value=0)
    where_sql = " WHERE " + " AND ".join(where)

    db = request_db()
    total = db.execute("SELECT COUNT(*) FROM products p" + where_sql, params).fetchone()[0]
    rows = db.execute(
        f"{_SELECT}{where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?",
        (*params, *order_params, limit, offset),
    ).fetchall()
    return jsonify({"items": [_to_dict(r) for r in rows], "total": total, "limit": limit, "offset": offset})


@products_bp.get("/kg")
def get_kg_product():
    """Vânzarea la kilogram: denumirea de pe bon și prețul unic pe kg (0 = încă nesetat)."""
    return jsonify(_kg_product(request_db()))


@products_bp.patch("/kg")
def update_kg_product():
    """Denumirea de pe bon și/sau prețul pe kg, pentru tot ce se vinde la kilogram."""
    data = read_json({"name", "price_bani"})
    fields = {
        "name": text(data, "name", 200),
        "price_bani": integer(data, "price_bani", min_value=1, max_value=MAX_PRICE_BANI),
    }
    fields = {k: v for k, v in fields.items() if v is not MISSING}
    if not fields:
        raise ApiError("Nimic de modificat")
    if "name" in fields:
        fields["search_name"] = search_key(fields["name"])
    db = request_db()
    sets = ", ".join(f"{col} = ?" for col in fields)
    db.execute(f"UPDATE products SET {sets}, updated_at = datetime('now','localtime') WHERE code = ?",
               (*fields.values(), KG_PRODUCT_CODE))
    db.commit()
    return jsonify(_kg_product(db))


@products_bp.get("/lookup")
def lookup_product():
    """Produsul activ cu exact acest cod sau cod de bare — tastat sau scanat la casă (KG = la kilogram)."""
    code = request.args.get("code", "").strip()
    if not code:
        raise ApiError("Parametrul 'code' este obligatoriu")
    row = request_db().execute(
        _SELECT + " WHERE p.active = 1 AND (p.code = ? OR p.barcode = ?) ORDER BY p.code = ? DESC LIMIT 1",
        (code, code, code),
    ).fetchone()
    if row is None:
        raise ApiError(f"Niciun produs activ cu codul „{code}”", 404)
    return jsonify(_to_dict(row))


@products_bp.get("/<id:product_id>")
def get_product(product_id):
    return jsonify(_get_product(request_db(), product_id))


@products_bp.post("/")
def create_product():
    data = read_json(_EDITABLE | _STOCK_FIELDS)
    if "stock_qty" in data:
        raise ApiError("La creare, stocul se trimite în 'initial_stock_qty'")
    fields = {**_read_fields(data, creating=True), "sale_type": "unit"}
    initial_stock = integer(data, "initial_stock_qty", min_value=0, max_value=MAX_QTY)

    db = request_db()
    cols = ", ".join(fields)
    marks = ", ".join("?" * len(fields))
    cur = _execute_unique(db, f"INSERT INTO products ({cols}) VALUES ({marks})", tuple(fields.values()), fields)
    if initial_stock is not MISSING and initial_stock > 0:
        db.execute(
            "INSERT INTO stock_movements (product_id, delta_qty, reason, note) "
            "VALUES (?, ?, 'receipt', 'Stoc inițial')",
            (cur.lastrowid, initial_stock),
        )
    db.commit()
    return jsonify(_get_product(db, cur.lastrowid)), 201


@products_bp.patch("/<id:product_id>")
def update_product(product_id):
    data = read_json(_EDITABLE | _STOCK_FIELDS)
    if _STOCK_FIELDS & data.keys():
        raise ApiError(f"Stocul nu se modifică direct — folosiți POST /api/products/{product_id}/stock")
    fields = _read_fields(data, creating=False)
    if not fields:
        raise ApiError("Nimic de modificat")

    db = request_db()
    _catalog_product(db, product_id)
    sets = ", ".join(f"{col} = ?" for col in fields)
    _execute_unique(
        db,
        f"UPDATE products SET {sets}, updated_at = datetime('now','localtime') WHERE id = ?",
        (*fields.values(), product_id),
        fields,
    )
    db.commit()
    return jsonify(_get_product(db, product_id))


@products_bp.delete("/<id:product_id>")
def delete_product(product_id):
    db = request_db()
    _catalog_product(db, product_id)
    try:
        db.execute("DELETE FROM products WHERE id = ?", (product_id,))
        db.commit()
        return jsonify({"deleted": "hard"})
    except sqlite3.IntegrityError:
        # Are istoric (mișcări de stoc sau bonuri) — doar dezactivat, ca bonurile
        # și rapoartele vechi să rămână corecte. Se reactivează cu PATCH active=true.
        db.rollback()
    db.execute(
        "UPDATE products SET active = 0, updated_at = datetime('now','localtime') WHERE id = ?", (product_id,)
    )
    db.commit()
    return jsonify({"deleted": "soft", "product": _get_product(db, product_id)})


@products_bp.post("/<id:product_id>/stock")
def add_stock_movement(product_id):
    """
    Mișcare manuală de stoc, în bucăți:
      receipt    → recepție marfă, delta_qty pozitiv
      adjustment → corecție (inventar, marfă stricată, sac deschis), orice semn
    """
    data = read_json({"delta_qty", "reason", "note"})
    reason = choice(data, "reason", MANUAL_STOCK_REASONS, required=True)
    delta = integer(data, "delta_qty", required=True, min_value=-MAX_QTY, max_value=MAX_QTY)
    note = text(data, "note", 500, nullable=True)
    if delta == 0:
        raise ApiError("Câmpul 'delta_qty' nu poate fi 0")
    if reason == "receipt" and delta < 0:
        raise ApiError("La recepție cantitatea trebuie să fie pozitivă — pentru scăderi folosiți 'adjustment'")

    db = request_db()
    _catalog_product(db, product_id)
    cur = db.execute(
        "INSERT INTO stock_movements (product_id, delta_qty, reason, note) VALUES (?, ?, ?, ?)",
        (product_id, delta, reason, note if isinstance(note, str) else ""),
    )
    db.commit()
    movement = db.execute(_MOVEMENT_SELECT + " WHERE id = ?", (cur.lastrowid,)).fetchone()
    return jsonify({"movement": dict(movement), "product": _get_product(db, product_id)}), 201


@products_bp.get("/<id:product_id>/movements")
def list_stock_movements(product_id):
    """Istoricul de stoc al produsului, cele mai noi primele."""
    limit = query_int("limit", 100, min_value=1, max_value=1000)
    offset = query_int("offset", 0, min_value=0)
    db = request_db()
    _get_product(db, product_id)
    total = db.execute("SELECT COUNT(*) FROM stock_movements WHERE product_id = ?", (product_id,)).fetchone()[0]
    rows = db.execute(
        _MOVEMENT_SELECT + " WHERE product_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
        (product_id, limit, offset),
    ).fetchall()
    return jsonify({"items": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset})
