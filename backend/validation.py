"""
Validarea datelor primite în cereri.

Reguli stricte, intenționat:
- câmpurile necunoscute sunt respinse — un "price" trimis în loc de
  "price_bani" dă eroare, nu e ignorat în tăcere;
- numerele trebuie să fie întregi JSON (1250, nu 12.5 sau "1250"), pentru
  că banii și cantitățile se țin în unități întregi (vezi database.py);
- un câmp absent din cerere întoarce MISSING, ca PATCH să modifice doar
  ce s-a trimis.
"""
import re
from datetime import date

from flask import request

from errors import ApiError

MISSING = object()
_INT64 = 2 ** 63  # limita unui INTEGER în SQLite — peste ea, sqlite3 aruncă OverflowError
_CUI_RE = re.compile(r"(RO)?([0-9]{2,10})")
_CUI_KEY = "753217532"  # cheia de test ANAF pentru cifra de control


def read_json(allowed):
    """Corpul cererii ca dict; respinge orice cheie din afara `allowed`."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Corpul cererii trebuie să fie un obiect JSON")
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise ApiError("Câmpuri necunoscute: " + ", ".join(unknown))
    return data


def text(data, key, max_len, required=False, nullable=False):
    """Text fără spații la capete. Gol sau null → None dacă nullable, altfel eroare."""
    if key not in data:
        if required:
            raise ApiError(f"Câmpul '{key}' este obligatoriu")
        return MISSING
    value = data[key]
    if value is not None and not isinstance(value, str):
        raise ApiError(f"Câmpul '{key}' trebuie să fie text")
    value = (value or "").strip()
    if not value:
        if nullable:
            return None
        raise ApiError(f"Câmpul '{key}' nu poate fi gol")
    if len(value) > max_len:
        raise ApiError(f"Câmpul '{key}' poate avea cel mult {max_len} caractere")
    return value


def integer(data, key, required=False, nullable=False, min_value=None, max_value=None):
    if key not in data:
        if required:
            raise ApiError(f"Câmpul '{key}' este obligatoriu")
        return MISSING
    value = data[key]
    if value is None and nullable:
        return None
    # bool e subclasă de int în Python — true/false nu trec drept numere
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(f"Câmpul '{key}' trebuie să fie un număr întreg")
    if min_value is not None and value < min_value:
        raise ApiError(f"Câmpul '{key}' trebuie să fie cel puțin {min_value}")
    if max_value is not None and value > max_value:
        raise ApiError(f"Câmpul '{key}' poate fi cel mult {max_value}")
    if not -_INT64 <= value < _INT64:
        raise ApiError(f"Câmpul '{key}' este în afara intervalului permis")
    return value


def boolean(data, key):
    if key not in data:
        return MISSING
    if not isinstance(data[key], bool):
        raise ApiError(f"Câmpul '{key}' trebuie să fie true sau false")
    return data[key]


def choice(data, key, options, required=False):
    if key not in data:
        if required:
            raise ApiError(f"Câmpul '{key}' este obligatoriu")
        return MISSING
    if data[key] not in options:
        raise ApiError(f"Câmpul '{key}' trebuie să fie unul dintre: {', '.join(options)}")
    return data[key]


def cui(data, key):
    """
    Cod fiscal românesc (CUI/CIF): opțional prefixul RO, apoi 2–10 cifre, ultima
    fiind cifra de control — o greșeală de tastare pe bonul unei firme e prinsă
    aici. Întoarce forma normalizată („ro 1408 0700” → „RO14080700”); gol → None.
    """
    value = text(data, key, 20, nullable=True)
    if not isinstance(value, str):
        return value  # MISSING sau None
    value = "".join(value.split()).upper()
    match = _CUI_RE.fullmatch(value)
    if not match or not _cui_check_digit_ok(match.group(2)):
        raise ApiError(f"Câmpul '{key}' nu este un cod fiscal (CUI) valid")
    return value


def _cui_check_digit_ok(digits):
    body = digits[:-1].rjust(9, "0")
    total = sum(int(d) * int(k) for d, k in zip(body, _CUI_KEY))
    return total * 10 % 11 % 10 == int(digits[-1])


def iso_date(data, key, required=False):
    """Dată AAAA-LL-ZZ din corpul cererii."""
    value = text(data, key, 10, required=required)
    if value is MISSING:
        return MISSING
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ApiError(f"Câmpul '{key}' trebuie să fie o dată AAAA-LL-ZZ") from None


def query_date(name, default):
    """Parametru dată din query string (?date_from=2026-10-01); absent → default."""
    raw = request.args.get(name, "").strip()
    if not raw:
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise ApiError(f"Parametrul '{name}' trebuie să fie o dată AAAA-LL-ZZ") from None


def query_int(name, default, min_value=None, max_value=None):
    """Parametru întreg din query string (?limit=50); absent → default."""
    raw = request.args.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ApiError(f"Parametrul '{name}' trebuie să fie un număr întreg") from None
    if min_value is not None and value < min_value:
        raise ApiError(f"Parametrul '{name}' trebuie să fie cel puțin {min_value}")
    if max_value is not None and value > max_value:
        raise ApiError(f"Parametrul '{name}' poate fi cel mult {max_value}")
    if not -_INT64 <= value < _INT64:
        raise ApiError(f"Parametrul '{name}' este în afara intervalului permis")
    return value
