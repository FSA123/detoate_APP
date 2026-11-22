from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from flask import Blueprint, jsonify

from database import request_db
from errors import ApiError
from routes.products import CATEGORY_NAMES
from validation import query_date

reports_bp = Blueprint("reports", __name__, url_prefix="/api/reports")

# Bonurile plătite în perioadă, după momentul plății; parametrii vin din period_params
PAID_IN_PERIOD = "o.status = 'paid' AND o.fiscalized_at >= ? AND o.fiscalized_at < ?"


def sales_period():
    """(date_from, date_to) din query string, ambele incluse; implicit azi."""
    date_to = query_date("date_to", date.today())
    date_from = query_date("date_from", date_to)
    if date_from > date_to:
        raise ApiError("Data de început este după data de sfârșit")
    return date_from, date_to


def period_params(date_from, date_to):
    return date_from.isoformat(), (date_to + timedelta(days=1)).isoformat()


def vat_included(gross_bani, percent):
    """TVA-ul conținut într-o sumă cu TVA inclus, rotunjit comercial: 121 lei la 21% → 21 lei."""
    rate = Decimal(str(percent))
    return int((Decimal(gross_bani) * rate / (100 + rate)).quantize(Decimal(1), ROUND_HALF_UP))


@reports_bp.get("/sales")
def sales_report():
    """
    Vânzările dintr-o perioadă (date_from, date_to: AAAA-LL-ZZ, incluse; implicit azi):
      totals          bonuri, total, numerar, card, câte dintre bonuri sunt simulate și
                      vat_bani — TVA-ul conținut în total (orientativ: casa calculează
                      TVA-ul oficial pe raportul Z)
      by_category     pe categorie — La bucată / La kilogram (felul vânzării, copiat pe bon)
      by_day          pe zile
      top_products    primele 20 după valoare
    """
    date_from, date_to = sales_period()
    params = period_params(date_from, date_to)
    db = request_db()

    totals = dict(db.execute(
        f"""
        SELECT COUNT(*) AS receipts,
               COALESCE(SUM(o.total_bani), 0) AS total_bani,
               COALESCE(SUM(CASE WHEN o.payment_method = 'cash' THEN o.total_bani END), 0) AS cash_bani,
               COALESCE(SUM(CASE WHEN o.payment_method = 'card' THEN o.total_bani END), 0) AS card_bani,
               COALESCE(SUM(o.fiscal_simulated), 0) AS simulated_receipts
          FROM orders o
         WHERE {PAID_IN_PERIOD}
        """,
        params,
    ).fetchone())

    by_category = db.execute(
        f"""
        SELECT i.sale_type, SUM(i.line_total_bani) AS total_bani, COUNT(*) AS lines
          FROM order_items i
          JOIN orders o ON o.id = i.order_id
         WHERE {PAID_IN_PERIOD}
         GROUP BY i.sale_type
         ORDER BY total_bani DESC, i.sale_type
        """,
        params,
    ).fetchall()

    # Pe cota copiată pe fiecare linie: azi e una singură (fiscal.VAT_PERCENT),
    # dar bonurile vechi rămân corecte dacă cota se schimbă vreodată
    totals["vat_bani"] = sum(vat_included(r["total_bani"], r["percent"]) for r in db.execute(
        f"""
        SELECT i.vat_percent AS percent, SUM(i.line_total_bani) AS total_bani
          FROM order_items i
          JOIN orders o ON o.id = i.order_id
         WHERE {PAID_IN_PERIOD}
         GROUP BY i.vat_percent
        """,
        params,
    ))

    by_day = db.execute(
        f"""
        SELECT substr(o.fiscalized_at, 1, 10) AS day, COUNT(*) AS receipts, SUM(o.total_bani) AS total_bani
          FROM orders o
         WHERE {PAID_IN_PERIOD}
         GROUP BY day
         ORDER BY day
        """,
        params,
    ).fetchall()

    top_products = db.execute(
        f"""
        SELECT i.product_id, p.code, p.name, i.sale_type,
               SUM(i.quantity_milli) AS quantity_milli, SUM(i.line_total_bani) AS total_bani
          FROM order_items i
          JOIN orders o ON o.id = i.order_id
          JOIN products p ON p.id = i.product_id
         WHERE {PAID_IN_PERIOD}
         GROUP BY i.product_id, i.sale_type
         ORDER BY total_bani DESC, p.name
         LIMIT 20
        """,
        params,
    ).fetchall()

    return jsonify({
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "totals": totals,
        "by_category": [{**dict(r), "name": CATEGORY_NAMES[r["sale_type"]]} for r in by_category],
        "by_day": [dict(r) for r in by_day],
        "top_products": [dict(r) for r in top_products],
    })
