"""
detoate.exe — toată aplicația într-un singur fișier, pentru calculatorul casei.
Construit cu PyInstaller: deploy/windows/build-exe.bat (rețeta: detoate.spec).

Lângă detoate.exe stă config.txt — creat la prima pornire, se modifică cu
Notepad. Datele (baza, jurnalul, copiile) stau în %LOCALAPPDATA%\\detoate,
deci înlocuirea lui detoate.exe la o actualizare nu le atinge.

    detoate.exe                       pornește casa: serverul + browserul (dacă
                                      rulează deja, doar deschide browserul)
    detoate.exe check-till [--bon]    verificarea casei de marcat (tremol_check.py)
    detoate.exe backup [--list]       o copie de siguranță acum / copiile existente
    detoate.exe restore FIȘIER        restaurează o copie — sau trageți copia .db
                                      peste detoate.exe (cu aplicația închisă)
"""
import os
import sys
import time
import urllib.request
import webbrowser

CONFIG_NAME = "config.txt"

CONFIG_TEMPLATE = """\
# Configurarea casei detoate. Se modifică cu Notepad; după o modificare închideți
# fereastra „detoate - server” și porniți din nou detoate.exe.

# --- Casa de marcat Tremol ---
# Portul găsit de „detoate.exe check-till” (ex. COM3). Gol = casa nu e conectată.
DETOATE_TREMOL_PORT=
# Tipul de plată pentru card, cum îl arată verificarea la pasul 6.
DETOATE_TREMOL_CARD_PAYMENT=1
# Viteza: se schimbă doar dacă verificarea a găsit casa la altă viteză.
DETOATE_TREMOL_BAUD=115200
# Probe fără casă: 1 = bonurile NU se tipăresc (sus apare MOD SIMULARE).
# În magazin rămâne GOL. Nu se setează împreună cu DETOATE_TREMOL_PORT.
DETOATE_FISCAL_SIMULATE=

# --- Copii de siguranță ---
# Încă un loc pentru fiecare copie, în afara calculatorului: un stick USB
# (ex. E:\\detoate-copii) sau un folder OneDrive. Gol = doar pe acest calculator.
DETOATE_BACKUP_COPY_DIR=
# Câte copii se păstrează și la câte ore se face una cât rulează aplicația.
DETOATE_BACKUP_KEEP=60
DETOATE_BACKUP_EVERY_HOURS=4

# --- Altele ---
# Adresa casei în browser: http://127.0.0.1:5000
DETOATE_PORT=5000
# 1 = pornește singură la deschiderea sesiunii Windows; 0 = nu.
DETOATE_AUTOSTART=1
# Unde stau datele. Gol = %LOCALAPPDATA%\\detoate. NU într-un folder sincronizat (OneDrive).
DETOATE_DATA_DIR=
"""

# Ce se poate pune în config.txt: cele din șablon, plus câteva pentru cazuri rare
KNOWN_KEYS = {
    line.split("=", 1)[0] for line in CONFIG_TEMPLATE.splitlines() if line.startswith("DETOATE_")
} | {"DETOATE_TREMOL_OPERATOR", "DETOATE_TREMOL_PASSWORD", "DETOATE_DB_PATH", "DETOATE_LOG_DIR",
     "DETOATE_BACKUP_DIR", "DETOATE_OPEN_BROWSER"}


def app_dir():
    """Folderul lui detoate.exe (sau al acestui fișier, rulat cu Python)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def load_config(path, environ):
    """
    Citește config.txt (îl creează din șablon dacă lipsește) în `environ`.
    O variabilă de mediu setată deja are întâietate (probe). Întoarce
    avertismentele: rânduri necunoscute sau fără „=”.
    """
    if not os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(CONFIG_TEMPLATE)
        except OSError as exc:
            return [f"{CONFIG_NAME} nu s-a putut crea lângă aplicație ({exc}) — merg cu setările implicite"]
    warnings = []
    with open(path, encoding="utf-8-sig") as f:  # -sig: Notepad poate salva cu BOM
        for number, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            key = key.strip()
            if not sep or key not in KNOWN_KEYS:
                warnings.append(f"{CONFIG_NAME}, rândul {number}: „{line}” nu e o setare cunoscută — ignorat")
                continue
            environ.setdefault(key, value.strip())
    return warnings


def apply_defaults(environ, frozen_dir=None):
    """Căile datelor (în afara folderului aplicației) și interfața din interiorul .exe."""
    data_dir = environ.get("DETOATE_DATA_DIR") or os.path.join(
        environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "detoate")
    environ["DETOATE_DATA_DIR"] = data_dir
    for key, default in (("DETOATE_DB_PATH", os.path.join(data_dir, "detoate.db")),
                         ("DETOATE_LOG_DIR", os.path.join(data_dir, "logs")),
                         ("DETOATE_BACKUP_DIR", os.path.join(data_dir, "backups"))):
        if not environ.get(key):
            environ[key] = default
    if frozen_dir:
        environ["DETOATE_FRONTEND_DIST"] = os.path.join(frozen_dir, "frontend_dist")


def _running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as r:
            return r.status == 200
    except OSError:
        return False


def sync_autostart(enabled, executable, startup_dir):
    """Pornirea automată: un .bat în folderul Startup al utilizatorului, cu calea de acum a .exe."""
    path = os.path.join(startup_dir, "detoate.bat")
    if not enabled:
        if os.path.exists(path):
            os.remove(path)
        return None
    content = f'@echo off\r\nstart "detoate" /min "{executable}"\r\n'
    try:
        with open(path, encoding="oem" if os.name == "nt" else "utf-8") as f:
            if f.read() == content:
                return path
    except (OSError, UnicodeError):
        pass
    with open(path, "w", encoding="oem" if os.name == "nt" else "utf-8", newline="") as f:
        f.write(content)
    return path


def run_server():
    port = int(os.environ.get("DETOATE_PORT") or 5000)
    if _running(port):  # pornită deja (de exemplu la deschiderea sesiunii): doar casa în browser
        webbrowser.open(f"http://127.0.0.1:{port}/")
        return 0
    if os.name == "nt":
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW("detoate - server (nu închideți această fereastră)")
        try:
            startup = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
            sync_autostart(os.environ.get("DETOATE_AUTOSTART", "1") != "0", sys.executable, startup)
        except (KeyError, OSError, UnicodeError) as exc:
            print(f"Atenție: pornirea automată nu s-a putut configura ({exc})", flush=True)
    os.environ.setdefault("DETOATE_OPEN_BROWSER", "1")

    import logging

    import serve
    while True:
        try:
            serve.main([])
        except KeyboardInterrupt:
            return 0
        except Exception:
            logging.getLogger("detoate").exception("Serverul s-a oprit neașteptat")
        # Ca vânzarea să nu rămână oprită: din nou, fără să mai deschidă browserul
        os.environ["DETOATE_OPEN_BROWSER"] = "0"
        print("\nServerul s-a oprit. Pornește din nou în 5 secunde — închideți fereastra pentru oprire.", flush=True)
        time.sleep(5)


def _command(argv):
    """Comenzile de întreținere; întoarce codul de ieșire."""
    name, rest = argv[0], argv[1:]
    if name == "check-till":
        import tremol_check
        return tremol_check.main(rest)
    import backup
    if name == "backup":
        return backup.main(rest)
    if name == "restore" and rest:
        return backup.main(["--restore", rest[0]])
    if name == "restore":
        return backup.main(["--list"])
    if name.lower().endswith(".db") and os.path.isfile(name):  # o copie trasă peste detoate.exe
        print(f"Restaurare din {name}\nBaza de acum se păstrează întâi ca o copie în plus.")
        if input("Scrieți DA pentru a continua: ").strip() != "DA":
            print("Nimic schimbat.")
            return 1
        return backup.main(["--restore", name])
    print(__doc__)
    return 0 if name in ("-h", "--help", "help") else 2


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    frozen = getattr(sys, "frozen", False)
    for warning in load_config(os.path.join(app_dir(), CONFIG_NAME), os.environ):
        print(f"Atenție: {warning}", flush=True)
    apply_defaults(os.environ, sys._MEIPASS if frozen else None)
    os.makedirs(os.environ["DETOATE_DATA_DIR"], exist_ok=True)

    if not argv:
        return run_server()
    code = _command(argv)
    if frozen:  # fereastra deschisă cu dublu-clic s-ar închide înainte să se poată citi rezultatul
        try:
            input("\nApăsați Enter pentru a închide fereastra.")
        except EOFError:
            pass
    return code


if __name__ == "__main__":
    sys.exit(main())
