import json
import logging
from datetime import date, timedelta

from flask import Blueprint, jsonify

import fiscal
from database import request_db
from errors import ApiError
from routes.orders import orders_lock
from validation import choice, iso_date, query_int, read_json

log = logging.getLogger(__name__)

fiscal_bp = Blueprint("fiscal", __name__, url_prefix="/api/fiscal")

REPORT_TYPES = ("X", "Z", "period")

_REPORT_SELECT = """
    SELECT id, type, z_number, date_from, date_to, total_bani, cash_bani, card_bani,
           simulated, response_json, created_at
      FROM fiscal_reports
"""


def _to_dict(row):
    report = dict(row)
    report["simulated"] = bool(report["simulated"])
    report["details"] = json.loads(report.pop("response_json"))
    return report


def _app_totals(db, where, params):
    """Ce a încasat aplicația pe bonurile plătite care îndeplinesc condiția."""
    row = db.execute(
        f"""
        SELECT COUNT(*) AS receipts,
               COALESCE(SUM(total_bani), 0) AS total_bani,
               COALESCE(SUM(CASE WHEN payment_method = 'cash' THEN total_bani END), 0) AS cash_bani,
               COALESCE(SUM(CASE WHEN payment_method = 'card' THEN total_bani END), 0) AS card_bani
          FROM orders
         WHERE status = 'paid' AND {where}
        """,
        params,
    ).fetchone()
    return dict(row)


def _on_device(action):
    try:
        return action()
    except fiscal.FiscalError as exc:
        raise ApiError(str(exc), 503) from None


@fiscal_bp.get("/status")
def fiscal_status():
    """Modul casei; interfața avertizează cât timp bonurile nu sunt reale sau nu se pot emite."""
    mode = fiscal.mode()
    return jsonify({"mode": mode, "simulated": mode == "simulate", "problem": fiscal.mode_problem()})


@fiscal_bp.get("/unreported")
def unreported_totals():
    """Ce ar cuprinde un raport Z acum: bonurile plătite (în modul curent) care nu sunt încă într-un Z."""
    simulated = fiscal.mode() == "simulate"
    totals = _app_totals(request_db(), "fiscal_simulated = ? AND fiscal_z_number IS NULL", (int(simulated),))
    return jsonify({**totals, "simulated": simulated})


@fiscal_bp.get("/reports")
def list_reports():
    """Jurnalul rapoartelor fiscale emise din aplicație, cele mai noi primele."""
    limit = query_int("limit", 50, min_value=1, max_value=500)
    offset = query_int("offset", 0, min_value=0)
    db = request_db()
    total = db.execute("SELECT COUNT(*) FROM fiscal_reports").fetchone()[0]
    rows = db.execute(_REPORT_SELECT + " ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    return jsonify({"items": [_to_dict(r) for r in rows], "total": total, "limit": limit, "offset": offset})


@fiscal_bp.post("/reports")
def create_report():
    """
    Raport tipărit pe casa de marcat, cu jurnal în fiscal_reports:
      {"type": "X"}       situația zilei, fără închidere
      {"type": "Z"}       închide ziua fiscală — IREVERSIBIL. Bonurile plătite
                          de la Z-ul precedent primesc numărul acestui Z.
      {"type": "period", "date_from": "2026-10-01", "date_to": "2026-10-19"}
                          raport scurt din memoria fiscală
    total/cash/card salvate sunt ale aplicației; ce raportează casa e în details.device.
    """
    data = read_json({"type", "date_from", "date_to"})
    kind = choice(data, "type", REPORT_TYPES, required=True)
    date_from = date_to = None
    if kind == "period":
        date_from = iso_date(data, "date_from", required=True)
        date_to = iso_date(data, "date_to", required=True)
        if date_from > date_to:
            raise ApiError("Data de început este după data de sfârșit")
        if date_to > date.today():
            raise ApiError("Perioada nu poate cuprinde zile viitoare")
    elif "date_from" in data or "date_to" in data:
        raise ApiError("Perioada se trimite doar la raportul 'period'")

    # Nicio vânzare cât timp casa tipărește raportul: Z-ul și bonurile marcate cu el trebuie să coincidă
    with orders_lock:
        db = request_db()
        simulated = fiscal.mode() == "simulate"
        if kind == "period":
            totals = _app_totals(
                db, "fiscal_simulated = ? AND fiscalized_at >= ? AND fiscalized_at < ?",
                (int(simulated), date_from.isoformat(), (date_to + timedelta(days=1)).isoformat()),
            )
            result = _on_device(lambda: fiscal.period_report(date_from, date_to))
        else:
            totals = _app_totals(db, "fiscal_simulated = ? AND fiscal_z_number IS NULL", (int(simulated),))
            result = _on_device(lambda: fiscal.daily_report(zeroing=kind == "Z"))
        if not result.ok:
            raise ApiError(result.message, 502)

        z_number = result.z_number
        if kind == "Z" and simulated:
            z_number = db.execute(
                "SELECT COALESCE(MAX(z_number), 0) + 1 FROM fiscal_reports WHERE type = 'Z' AND simulated = 1"
            ).fetchone()[0]
        device = None
        if result.total_bani is not None:
            device = {"total_bani": result.total_bani, "cash_bani": result.cash_bani, "card_bani": result.card_bani}
        details = {"receipts": totals["receipts"], "device": device, "message": result.message, "raw": result.raw}

        # De aici raportul există pe casă — o eroare la salvare trebuie să se vadă în log
        try:
            cur = db.execute(
                "INSERT INTO fiscal_reports (type, z_number, date_from, date_to, total_bani, cash_bani, "
                "card_bani, simulated, response_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kind, z_number, date_from and date_from.isoformat(), date_to and date_to.isoformat(),
                 totals["total_bani"], totals["cash_bani"], totals["card_bani"], int(simulated),
                 json.dumps(details, ensure_ascii=False)),
            )
            if kind == "Z" and z_number is not None:
                db.execute(
                    "UPDATE orders SET fiscal_z_number = ? "
                    "WHERE status = 'paid' AND fiscal_z_number IS NULL AND fiscal_simulated = ?",
                    (z_number, int(simulated)),
                )
            db.commit()
        except Exception:
            log.critical("Raportul %s a fost tipărit pe casă, dar NU s-a salvat în aplicație", kind)
            raise

        row = db.execute(_REPORT_SELECT + " WHERE id = ?", (cur.lastrowid,)).fetchone()
        return jsonify(_to_dict(row)), 201
