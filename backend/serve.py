"""
Pornirea aplicației în magazin: serverul de producție waitress (nu serverul de
dezvoltare Flask), interfața construită servită de Flask, jurnal în fișier și
copii automate ale bazei de date. În magazin îl pornește detoate.exe (detoate_exe.py).

    python serve.py              pornește serverul pe http://127.0.0.1:5000
    python serve.py --init-only  doar creează / actualizează baza de date (la instalare)

Variabile (în magazin, în config.txt lângă detoate.exe):
  DETOATE_DB_PATH, DETOATE_PORT, cele ale casei de marcat (vezi fiscal.py),
  cele ale copiilor de siguranță (vezi backup.py), plus:
  DETOATE_LOG_DIR             jurnalul (implicit logs/ lângă baza de date)
  DETOATE_BACKUP_EVERY_HOURS  la câte ore se face o copie cât rulează serverul (implicit 4)
  DETOATE_OPEN_BROWSER=1      deschide casa în browser după pornire
"""
import argparse
import logging
import os
import sys
import threading
import webbrowser
from logging.handlers import RotatingFileHandler

import backup
import database

log = logging.getLogger("detoate")


def _setup_logging():
    log_dir = os.environ.get("DETOATE_LOG_DIR") or os.path.join(os.path.dirname(os.path.abspath(database.DB_PATH)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            RotatingFileHandler(os.path.join(log_dir, "detoate.log"), maxBytes=5_000_000, backupCount=5, encoding="utf-8"),
        ],
    )
    return log_dir


def backup_loop(every_hours, stop, check_seconds=60):
    """O copie la pornire, apoi la fiecare `every_hours` ore cât rulează serverul."""
    while not stop.is_set():
        try:
            if backup.is_due(every_hours):
                backup.run()
        except Exception:
            # Copia nu are voie să oprească vânzarea; eroarea rămâne în jurnal
            log.exception("Copia de siguranță a bazei de date a eșuat")
        stop.wait(check_seconds)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pornește aplicația detoate (server de producție).")
    parser.add_argument("--init-only", action="store_true", help="doar pregătește baza de date, apoi iese")
    args = parser.parse_args(argv)

    os.makedirs(os.path.dirname(os.path.abspath(database.DB_PATH)), exist_ok=True)
    log_dir = _setup_logging()
    database.init_db()
    if args.init_only:
        log.info("Baza de date e pregătită: %s", database.DB_PATH)
        return 0

    # După configurarea jurnalului: avertismentele casei de marcat de la import ajung și în fișier
    from waitress import serve

    import fiscal
    from app import app

    port = int(os.environ.get("DETOATE_PORT", "5000"))
    url = f"http://127.0.0.1:{port}/"
    log.info("detoate pornește pe %s — casa de marcat: %s; baza de date: %s; jurnal: %s",
             url, fiscal.mode(), database.DB_PATH, log_dir)
    if fiscal.mode_problem():
        log.warning(fiscal.mode_problem())

    every_hours = float(os.environ.get("DETOATE_BACKUP_EVERY_HOURS", "4"))
    threading.Thread(target=backup_loop, args=(every_hours, threading.Event()), daemon=True, name="backup").start()
    if os.environ.get("DETOATE_OPEN_BROWSER") == "1":
        threading.Timer(2, webbrowser.open, [url]).start()

    # Doar pe calculatorul casei (127.0.0.1): API-ul nu are autentificare
    serve(app, host="127.0.0.1", port=port, threads=8, ident="detoate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
