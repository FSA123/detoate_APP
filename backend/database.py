import sqlite3
import os
from typing import Optional

from flask import g

from search import search_key

# ─── Cale configurabilă — poate fi suprascrisă prin variabilă de mediu ────────
DB_PATH = os.environ.get(
    "DETOATE_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "detoate.db")
)

# ─── Convenții de stocare ─────────────────────────────────────────────────────
# Fără REAL pentru bani sau cantități — totul e INTEGER, ca să nu apară erori
# de rotunjire float pe bonul fiscal:
#   *_bani   → sume în bani (1 leu = 100 bani). 12,50 lei = 1250
#   *_milli  → cantități vândute (linii de bon), în miimi de unitate — casa de
#              marcat lucrează cu 3 zecimale
#              produs la kg:  1 kg = 1000   (deci practic grame)
#              produs la buc: 1 buc = 1000
#   *_qty    → stoc, în bucăți întregi (saci, lăzi, bucăți) — inclusiv pentru
#              produsele vândute la kg. Detalii la tabela products.
#   Preț produs = preț pe unitate (pe kg sau pe bucată).
#   Total linie = quantity_milli * unit_price_bani / 1000, rotunjit comercial
#                 (0,5 bani în sus, ca pe casă) — routes/orders.line_total_bani.
#                 NU round() din Python: acela rotunjește 0,5 spre par.

# ─── Vânzarea la kilogram ─────────────────────────────────────────────────────
# Tot ce se vinde la kg are UN singur preț pe kilogram, oricare ar fi marfa.
# E un rând fix în products (sale_type 'weight', codul KG), creat aici la
# prima pornire, fără preț: casa refuză vânzarea la kg până se setează prețul
# (Produse → La kilogram). Catalogul propriu-zis are doar produse la bucată.
KG_PRODUCT_CODE = "KG"
KG_PRODUCT_NAME = "Marfă la kilogram"


def get_db():
    """
    Deschide o conexiune SQLite cu toate PRAGMAurile necesare.
    - foreign_keys: integritate referențială aplicată
    - timeout 30s: nu blochează la infinit dacă DB e ocupat
    """
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def request_db():
    """
    Conexiunea cererii HTTP curente — deschisă la prima folosire și închisă
    automat la finalul cererii (close_request_db, înregistrat în app.py).
    Ce nu a fost comis până atunci se anulează.
    """
    if "db" not in g:
        g.db = get_db()
    return g.db


def close_request_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path: Optional[str] = None):
    """
    Creează schema. Idempotent (IF NOT EXISTS) — rulat la fiecare pornire.
    """
    conn = sqlite3.connect(path or DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row

    # Nu în executescript() pentru că pragma nu funcționează în tranzacții
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -8000")
    conn.execute("PRAGMA temp_store = MEMORY")

    # O bază dintr-o versiune mai veche (cota TVA aleasă pe fiecare produs) nu se
    # convertește singură, iar produsele noi n-ar mai putea fi salvate în ea —
    # oprim clar la pornire, în loc de erori la prima salvare.
    if conn.execute("SELECT 1 FROM pragma_table_info('products') WHERE name = 'vat_rate_id'").fetchone():
        conn.close()
        raise RuntimeError(
            f"Baza de date {path or DB_PATH} e dintr-o versiune mai veche a aplicației (cote TVA pe produs). "
            "Mutați fișierul deoparte și porniți din nou: aplicația creează o bază nouă, goală."
        )

    cur = conn.cursor()

    # ── Tabele ────────────────────────────────────────────────────────────────
    cur.executescript("""
        -- Catalogul de produse.
        --   sale_type 'unit'   → vândut la bucată: toate produsele adăugate de magazin
        --   sale_type 'weight' → vândut la kg: doar rândul fix KG_PRODUCT_CODE (sus)
        -- sale_type e și categoria din rapoarte: „La bucată” / „La kilogram”.
        -- TVA-ul nu e pe produs: e o singură cotă, fixă, pentru tot (fiscal.VAT_PERCENT).
        -- Stocul se ține în bucăți întregi (stock_qty), pentru toate produsele:
        --   'unit'   → vânzarea scade automat bucățile vândute
        --   'weight' → vânzarea NU scade stocul; bucățile (saci, lăzi) intră
        --              la recepție și ies prin ajustare manuală (ex. sac deschis)
        -- stock_qty e un cache al sumei din stock_movements, ținut la zi de
        -- triggerul de mai jos. Poate deveni negativ: magazinul nu trebuie
        -- blocat la casă dacă recepția n-a fost introdusă încă.
        -- Ștergerea e soft (active = 0) pentru că bonurile vechi îl referă.
        CREATE TABLE IF NOT EXISTS products (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            code            TEXT    NOT NULL UNIQUE,       -- număr produs / PLU, tastat la casă
            barcode         TEXT    UNIQUE,                -- opțional, pentru scanner
            name            TEXT    NOT NULL,
            search_name     TEXT    NOT NULL DEFAULT '',   -- name fără diacritice, litere mici (search.search_key), setat de aplicație
            sale_type       TEXT    NOT NULL CHECK(sale_type IN ('weight','unit')),
            price_bani      INTEGER NOT NULL CHECK(price_bani >= 0),   -- pe kg sau pe buc
            stock_qty       INTEGER NOT NULL DEFAULT 0,                -- bucăți
            min_stock_qty   INTEGER NOT NULL DEFAULT 0 CHECK(min_stock_qty >= 0),
            active          INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        );

        -- Registrul de stoc: orice mișcare (recepție, vânzare, ajustare, retur)
        -- e o linie aici, în bucăți. Sursa de adevăr pentru stoc;
        -- products.stock_qty e doar suma, pentru citire rapidă.
        CREATE TABLE IF NOT EXISTS stock_movements (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id  INTEGER NOT NULL,
            delta_qty   INTEGER NOT NULL CHECK(delta_qty <> 0),   -- + intrare / − ieșire
            reason      TEXT    NOT NULL
                                CHECK(reason IN ('receipt','sale','adjustment','return','cancel')),
            order_id    INTEGER,
            note        TEXT    NOT NULL DEFAULT '',
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
            FOREIGN KEY (order_id)   REFERENCES orders(id)   ON DELETE SET NULL
        );

        -- Clienți salvați — în special firme (persoană juridică), ca să nu
        -- se tasteze CUI-ul la fiecare bon. Persoana fizică anonimă nu are
        -- nevoie de rând aici (orders.customer_id = NULL).
        CREATE TABLE IF NOT EXISTS customers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            type       TEXT    NOT NULL CHECK(type IN ('pf','pj')),
            name       TEXT    NOT NULL,
            cui        TEXT,                               -- obligatoriu pentru pj
            reg_com    TEXT    NOT NULL DEFAULT '',
            address    TEXT    NOT NULL DEFAULT '',
            created_at TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            CHECK(type = 'pf' OR (cui IS NOT NULL AND cui <> ''))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_cui
            ON customers(cui) WHERE cui IS NOT NULL;

        -- Comanda / bonul.
        --   pending   → coș deschis, încă se modifică
        --   paid      → plătit și fiscalizat (bon emis)
        --   cancelled → anulat înainte de plată
        -- Datele cumpărătorului sunt copiate (buyer_*) la momentul plății:
        -- dacă firma își schimbă adresa, bonul vechi rămâne neschimbat.
        CREATE TABLE IF NOT EXISTS orders (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            status                TEXT    NOT NULL DEFAULT 'pending'
                                          CHECK(status IN ('pending','paid','cancelled')),
            buyer_type            TEXT    NOT NULL DEFAULT 'pf' CHECK(buyer_type IN ('pf','pj')),
            customer_id           INTEGER,
            buyer_name            TEXT    NOT NULL DEFAULT '',
            buyer_cui             TEXT    NOT NULL DEFAULT '',
            total_bani            INTEGER NOT NULL DEFAULT 0 CHECK(total_bani >= 0),
            payment_method        TEXT    CHECK(payment_method IN ('cash','card')),
            cash_received_bani    INTEGER CHECK(cash_received_bani >= 0),
            fiscal_receipt_number TEXT,
            fiscal_z_number       INTEGER,                 -- în ce raport Z a intrat bonul
            fiscalized_at         TEXT,
            -- 1 = emis în modul simulare (DETOATE_FISCAL_SIMULATE): bonul NU
            -- există pe casa de marcat, deci nici în rapoartele ei
            fiscal_simulated      INTEGER NOT NULL DEFAULT 0 CHECK(fiscal_simulated IN (0,1)),
            notes                TEXT    NOT NULL DEFAULT '',
            created_at            TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at            TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE SET NULL,
            CHECK(buyer_type = 'pf' OR buyer_cui <> ''),
            CHECK(status <> 'paid' OR payment_method IS NOT NULL)
        );

        -- Liniile bonului. Totul e copiat la adăugare (nume, tip, preț de listă
        -- din produs; grupa și cota TVA fixe din fiscal.py), ca bonul să rămână
        -- corect chiar dacă produsul sau cota se schimbă ulterior.
        --   list_price_bani   → prețul din catalog în acel moment; nu se mai schimbă
        --   manual_price_bani → prețul nou tastat de casier („Modificare preț”),
        --                       în locul celui din catalog; NULL = nu e
        --   discount_bp       → reducerea dată de casier, în sutimi de procent
        --                       (10% = 1000, 12,5% = 1250); 0 = fără reducere
        --   unit_price_bani   → prețul încasat: (manual_price_bani sau, fără el,
        --                       list_price_bani) minus reducerea, rotunjit comercial
        --                       (routes/orders.discounted_price). Ex.: 120 lei →
        --                       preț nou 100 → reducere 30% → 70 lei
        --   price_overridden  → calculat: prețul încasat diferă de cel din catalog
        CREATE TABLE IF NOT EXISTS order_items (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id         INTEGER NOT NULL,
            product_id       INTEGER NOT NULL,
            product_name     TEXT    NOT NULL,
            sale_type        TEXT    NOT NULL CHECK(sale_type IN ('weight','unit')),
            quantity_milli   INTEGER NOT NULL CHECK(quantity_milli > 0),
            list_price_bani  INTEGER NOT NULL CHECK(list_price_bani >= 0),
            unit_price_bani  INTEGER NOT NULL CHECK(unit_price_bani >= 0),
            price_overridden INTEGER GENERATED ALWAYS AS (unit_price_bani <> list_price_bani) VIRTUAL,
            vat_fiscal_code  TEXT    NOT NULL,
            vat_percent      REAL    NOT NULL,
            line_total_bani  INTEGER NOT NULL CHECK(line_total_bani >= 0),
            discount_bp      INTEGER NOT NULL DEFAULT 0 CHECK(discount_bp >= 0 AND discount_bp < 10000),
            manual_price_bani INTEGER CHECK(manual_price_bani IS NULL OR manual_price_bani > 0),
            FOREIGN KEY (order_id)   REFERENCES orders(id)   ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE RESTRICT,
            -- produsele la bucată se vând doar în bucăți întregi
            CHECK(sale_type = 'weight' OR quantity_milli % 1000 = 0)
        );

        -- Jurnalul rapoartelor fiscale emise din aplicație (X, Z, raport pe
        -- perioadă din memoria fiscală). Totalurile returnate de casă sunt
        -- păstrate brut în response_json pentru audit.
        CREATE TABLE IF NOT EXISTS fiscal_reports (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            type          TEXT    NOT NULL CHECK(type IN ('X','Z','period')),
            z_number      INTEGER,
            date_from     TEXT,
            date_to       TEXT,
            total_bani    INTEGER,
            cash_bani     INTEGER,
            card_bani     INTEGER,
            simulated     INTEGER NOT NULL DEFAULT 0 CHECK(simulated IN (0,1)),
            response_json TEXT    NOT NULL DEFAULT '{}',
            created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            CHECK(type <> 'period' OR (date_from IS NOT NULL AND date_to IS NOT NULL))
        );
    """)

    # ── Coloane adăugate după lansare: o bază mai veche le primește aici ──────
    if not cur.execute("SELECT 1 FROM pragma_table_info('order_items') WHERE name = 'discount_bp'").fetchone():
        cur.execute("ALTER TABLE order_items ADD COLUMN discount_bp INTEGER NOT NULL DEFAULT 0 "
                    "CHECK(discount_bp >= 0 AND discount_bp < 10000)")
    if not cur.execute("SELECT 1 FROM pragma_table_info('order_items') WHERE name = 'manual_price_bani'").fetchone():
        # Într-o singură tranzacție: coloana și completarea ei. Liniile de dinainte,
        # cu preț tastat de mână (fără reducere), își păstrează prețul ca „preț nou”.
        cur.executescript("""
            BEGIN;
            ALTER TABLE order_items ADD COLUMN manual_price_bani INTEGER
                CHECK(manual_price_bani IS NULL OR manual_price_bani > 0);
            UPDATE order_items SET manual_price_bani = unit_price_bani
             WHERE discount_bp = 0 AND unit_price_bani <> list_price_bani AND unit_price_bani > 0;
            COMMIT;
        """)

    # ── Triggere ──────────────────────────────────────────────────────────────
    # Stocul din products e actualizat automat la fiecare mișcare — codul
    # aplicației scrie doar în stock_movements, niciodată direct în stock_qty.
    cur.executescript("""
        CREATE TRIGGER IF NOT EXISTS trg_stock_movement_apply
        AFTER INSERT ON stock_movements
        BEGIN
            UPDATE products
               SET stock_qty  = stock_qty + NEW.delta_qty,
                   updated_at = datetime('now','localtime')
             WHERE id = NEW.product_id;
        END;
    """)

    # ── Indecși ───────────────────────────────────────────────────────────────
    cur.executescript("""
        CREATE INDEX IF NOT EXISTS idx_products_name       ON products(name);
        CREATE INDEX IF NOT EXISTS idx_products_active     ON products(active);
        CREATE INDEX IF NOT EXISTS idx_stock_mov_product   ON stock_movements(product_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_orders_status       ON orders(status);
        CREATE INDEX IF NOT EXISTS idx_orders_created      ON orders(created_at);
        CREATE INDEX IF NOT EXISTS idx_orders_fiscalized   ON orders(fiscalized_at);
        CREATE INDEX IF NOT EXISTS idx_order_items_order   ON order_items(order_id);
        CREATE INDEX IF NOT EXISTS idx_fiscal_reports_type ON fiscal_reports(type, created_at);
    """)

    # ── Rândul fix pentru vânzarea la kilogram (vezi KG_PRODUCT_CODE) ─────────
    cur.execute(
        "INSERT OR IGNORE INTO products (code, name, search_name, sale_type, price_bani) "
        "VALUES (?, ?, ?, 'weight', 0)",
        (KG_PRODUCT_CODE, KG_PRODUCT_NAME, search_key(KG_PRODUCT_NAME)),
    )

    conn.commit()
    conn.close()
