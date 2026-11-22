"""
Copiile de siguranță ale bazei de date.

    python backup.py                    o copie acum
    python backup.py --list             copiile existente, cele mai noi primele
    python backup.py --restore FIȘIER   înlocuiește baza cu o copie (aplicația trebuie oprită)

Copia se face cu API-ul de backup al SQLite — sigur și cu aplicația pornită (o
copiere simplă a fișierului poate prinde baza la jumătatea unei scrieri) — și e
păstrată doar dacă trece PRAGMA integrity_check. Serverul (serve.py) face singur
o copie la pornire și apoi la câteva ore.

Variabile:
  DETOATE_BACKUP_DIR        unde stau copiile (implicit backups/ lângă baza de date)
  DETOATE_BACKUP_KEEP       câte copii se păstrează (implicit 60)
  DETOATE_BACKUP_COPY_DIR   opțional: încă un loc pentru fiecare copie (stick USB,
                            folder OneDrive) — dacă lipsește, copia principală tot se face
"""
import argparse
import glob
import logging
import os
import shutil
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime

import database

log = logging.getLogger("detoate.backup")

PREFIX = "detoate-"


def backup_dir():
    return os.environ.get("DETOATE_BACKUP_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(database.DB_PATH)), "backups")


def _keep():
    return max(1, int(os.environ.get("DETOATE_BACKUP_KEEP", "60")))


def list_backups(directory=None):
    """Copiile din folder, cele mai noi primele (numele conține data și ora)."""
    return sorted(glob.glob(os.path.join(directory or backup_dir(), f"{PREFIX}*.db")), reverse=True)


def is_due(every_hours):
    """Nicio copie, sau cea mai nouă e mai veche de `every_hours` ore."""
    backups = list_backups()
    return not backups or time.time() - os.path.getmtime(backups[0]) >= every_hours * 3600


def _check(path):
    """Mesajul de eroare pentru un fișier care nu e o bază detoate întreagă, sau None."""
    try:
        # immutable: fără fișiere -wal/-shm, deci merge și pe o copie dintr-o bază în modul WAL
        conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return f"nu e o bază de date SQLite ({exc})"
    if result != "ok":
        return f"nu trece verificarea de integritate ({result})"
    if not {"products", "orders", "order_items"} <= tables:
        return "nu e o bază de date detoate"
    return None


def _prune(directory):
    for old in list_backups(directory)[_keep():]:
        os.remove(old)


def run():
    """O copie verificată a bazei de date; întoarce calea ei."""
    if not os.path.exists(database.DB_PATH):
        raise FileNotFoundError(f"baza de date nu există: {database.DB_PATH}")
    directory = backup_dir()
    os.makedirs(directory, exist_ok=True)
    # Cu milisecunde: două copii în aceeași secundă nu se suprascriu, iar numele rămân în ordine cronologică
    now = datetime.now()
    final = os.path.join(directory, f"{PREFIX}{now:%Y-%m-%d_%H%M%S}-{now.microsecond // 1000:03d}.db")
    partial = final + ".partial"
    source = sqlite3.connect(database.DB_PATH, timeout=30)
    try:
        target = sqlite3.connect(partial)
        try:
            source.backup(target)
            # Copia moștenește modul WAL al bazei; ca fișier unic, de sine stătător, se poate muta oriunde
            target.execute("PRAGMA journal_mode = DELETE")
        finally:
            target.close()
    finally:
        source.close()
    # Fișierele -wal/-shm din faza WAL a copiei pot rămâne; altfel s-ar aduna câte unul la fiecare copie
    for suffix in ("-wal", "-shm"):
        if os.path.exists(partial + suffix):
            os.remove(partial + suffix)
    problem = _check(partial)
    if problem:
        os.remove(partial)
        raise RuntimeError(f"copia {final} {problem}")
    os.replace(partial, final)
    _prune(directory)

    extra = os.environ.get("DETOATE_BACKUP_COPY_DIR")
    if extra:
        try:
            os.makedirs(extra, exist_ok=True)
            shutil.copy2(final, extra)
            _prune(extra)
        except OSError as exc:
            log.warning("Copia nu s-a putut pune și în %s (stick scos, disc plin?): %s", extra, exc)
    log.info("Copie a bazei de date: %s", final)
    return final


def server_running():
    port = os.environ.get("DETOATE_PORT", "5000")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1):
            return True
    except OSError:
        return False


def restore(path):
    """
    Înlocuiește baza de date cu copia `path`. Baza de acum se salvează întâi ca o
    copie în plus, deci o restaurare greșită se poate desface. Întoarce calea acelei copii.
    """
    if server_running():
        raise RuntimeError("aplicația rulează — închideți fereastra serverului, apoi reîncercați")
    problem = _check(path)
    if problem:
        raise RuntimeError(f"{path} {problem}")
    os.makedirs(os.path.dirname(os.path.abspath(database.DB_PATH)), exist_ok=True)
    # Întâi copia de restaurat, deoparte — copia de siguranță de mai jos nu o mai poate atinge
    incoming = database.DB_PATH + ".restore"
    shutil.copy2(path, incoming)
    saved = run() if os.path.exists(database.DB_PATH) else None
    # Jurnalul WAL al bazei vechi nu are voie să se aplice peste cea restaurată
    for suffix in ("-wal", "-shm"):
        if os.path.exists(database.DB_PATH + suffix):
            os.remove(database.DB_PATH + suffix)
    os.replace(incoming, database.DB_PATH)
    log.info("Baza de date restaurată din %s", path)
    return saved


def main(argv=None):
    parser = argparse.ArgumentParser(description="Copiile de siguranță ale bazei de date detoate.")
    parser.add_argument("--list", action="store_true", help="arată copiile existente")
    parser.add_argument("--restore", metavar="FIȘIER", help="înlocuiește baza de date cu această copie")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        if args.list:
            for path in list_backups():
                print(f"{os.path.basename(path)}  {os.path.getsize(path) // 1024} KB")
            print(f"({backup_dir()})")
        elif args.restore:
            saved = restore(args.restore)
            print(f"Restaurat din {args.restore}.")
            if saved:
                print(f"Baza dinainte e păstrată în {saved}.")
            print("Porniți din nou aplicația.")
        else:
            print(f"Copie făcută: {run()}")
    except (OSError, RuntimeError) as exc:
        print(f"EROARE: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
