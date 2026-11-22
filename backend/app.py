import logging
import os

from flask import Flask, jsonify, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.routing import IntegerConverter

from database import close_request_db, init_db
from errors import ApiError
from routes.excel import excel_bp
from routes.fiscal import fiscal_bp
from routes.orders import orders_bp
from routes.products import products_bp
from routes.reports import reports_bp


class IdConverter(IntegerConverter):
    """<id:...> în rute: întreg pozitiv care încape în SQLite — altfel 404, nu eroare 500."""

    def __init__(self, url_map):
        super().__init__(url_map, min=1, max=2 ** 63 - 1)


app = Flask(__name__)
app.url_map.strict_slashes = False
app.url_map.converters["id"] = IdConverter
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # importul Excel
# Diacriticele rămân lizibile în răspunsuri (curl, consolă); cheile în ordinea din cod
app.json.ensure_ascii = False
app.json.sort_keys = False

# Fără antete CORS, intenționat: interfața e servită de pe aceeași origine
# (proxy Vite în dezvoltare, Flask în producție). Cu CORS "*", orice site
# deschis în browserul de la casă ar putea trimite cereri către API.
app.register_blueprint(products_bp)
app.register_blueprint(orders_bp)
app.register_blueprint(fiscal_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(excel_bp)

app.teardown_appcontext(close_request_db)

_HTTP_MESSAGES = {
    400: "Cerere invalidă",
    404: "Resursa nu există",
    405: "Metodă HTTP nepermisă pentru această adresă",
    413: "Fișierul este prea mare (maximum 10 MB)",
}


@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify({"error": e.message, **e.extra}), e.status


@app.errorhandler(HTTPException)
def handle_http_error(e):
    return jsonify({"error": _HTTP_MESSAGES.get(e.code, e.name)}), e.code


@app.errorhandler(Exception)
def handle_unexpected_error(e):
    app.logger.exception("Eroare neprevăzută")
    return jsonify({"error": "Eroare internă a serverului"}), 500


@app.get("/api/health")
def health():
    return {"status": "ok"}


# ─── Interfața, în producție ──────────────────────────────────────────────────
# Construită cu „npm run build” în frontend/ (în dezvoltare o servește Vite).
FRONTEND_DIST = os.environ.get(
    "DETOATE_FRONTEND_DIST",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist"),
)


@app.get("/")
def index():
    if not os.path.isfile(os.path.join(FRONTEND_DIST, "index.html")):
        message = "Interfața nu este construită: rulați „npm run build” în folderul frontend."
        return message, 503, {"Content-Type": "text/plain; charset=utf-8"}
    response = send_from_directory(FRONTEND_DIST, "index.html")
    response.cache_control.no_cache = True  # o versiune nouă a aplicației se vede la primul refresh
    return response


@app.get("/favicon.svg")
def favicon():
    return send_from_directory(FRONTEND_DIST, "favicon.svg", max_age=24 * 3600)


@app.get("/assets/<path:filename>")
def assets(filename):
    # Numele fișierelor conțin un hash al conținutului, deci pot sta în cache oricât
    return send_from_directory(os.path.join(FRONTEND_DIST, "assets"), filename, max_age=365 * 24 * 3600)


if __name__ == "__main__":
    # INFO, ca bonurile din modul simulare să apară în consolă
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    app.run(debug=True, host="127.0.0.1", port=int(os.environ.get("DETOATE_PORT", "5000")))
