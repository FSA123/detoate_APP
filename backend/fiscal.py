"""
Casa de marcat, văzută din aplicație: send_receipt(receipt) pentru bonuri,
daily_report(zeroing) și period_report(de la, până la) pentru rapoarte.

Ce casă e dedesubt se alege din variabile de mediu — restul aplicației nu știe:
  DETOATE_FISCAL_SIMULATE=1    nimic nu se tipărește; succes fals (bon SIM-<id
                               comandă>), bonul apare în log. Pentru laptop.
  DETOATE_TREMOL_PORT=COM3     casa Tremol reală, pe port serial / USB (tremol.py)
    DETOATE_TREMOL_BAUD          implicit 115200
    DETOATE_TREMOL_OPERATOR      implicit 1
    DETOATE_TREMOL_PASSWORD      implicit 0000
    DETOATE_TREMOL_CARD_PAYMENT  tipul de plată programat pe casă pentru card,
                                 implicit 1 — verificat cu tremol_check.py
  niciuna                      plata eșuează cu mesaj clar
  amândouă                     refuzat: o greșeală de configurare nu decide în
                               tăcere între bonuri reale și simulate

Implicit NU e simulare, intenționat: dacă variabila lipsește în magazin, plata
eșuează, în loc să marcheze comenzi ca plătite fără ca bonul să existe pe casă.

Contractul: un Receipt intră, un FiscalResult (ok, doc_number, receipt_number,
message, raw) iese. ok=False înseamnă că bonul NU s-a emis și comanda rămâne
neplătită; FiscalError, că nu s-a putut vorbi cu casa. Sumele rămân în bani și
miimi, ca în baza de date; zecimalele și scurtarea numelor sunt treaba adaptorului.
"""
import logging
import os
from dataclasses import dataclass, field
from typing import Optional, Tuple

import tremol

log = logging.getLogger(__name__)

SIMULATE = os.environ.get("DETOATE_FISCAL_SIMULATE", "0").strip().lower() not in ("", "0", "false", "no")
TREMOL_PORT = os.environ.get("DETOATE_TREMOL_PORT", "").strip()
TREMOL_BAUD = int(os.environ.get("DETOATE_TREMOL_BAUD", "115200"))
TREMOL_OPERATOR = os.environ.get("DETOATE_TREMOL_OPERATOR", "1").strip()
TREMOL_PASSWORD = os.environ.get("DETOATE_TREMOL_PASSWORD", "0000").strip()
TREMOL_CARD_PAYMENT = os.environ.get("DETOATE_TREMOL_CARD_PAYMENT", "1").strip()

# Singura cotă TVA a magazinului: 21%, pe grupa A a casei de marcat — fixă în cod,
# fără alte cote în aplicație. Se copiază pe fiecare linie de bon (order_items),
# deci o schimbare viitoare nu modifică istoricul. tremol_check.py verifică că
# grupa A de pe casă are exact această cotă.
VAT_GROUP = "A"
VAT_PERCENT = 21.0

_MODE_ERRORS = {
    "none": (
        "Casa de marcat nu este configurată. Setați DETOATE_TREMOL_PORT pentru casa reală "
        "sau, pentru testare fără casă, porniți serverul cu DETOATE_FISCAL_SIMULATE=1"
    ),
    "conflict": (
        "Sunt setate și DETOATE_FISCAL_SIMULATE, și DETOATE_TREMOL_PORT — păstrați doar una, "
        "ca să fie clar dacă bonurile sunt reale"
    ),
}


class FiscalError(Exception):
    """Casa nu poate fi folosită (neconfigurată, nu răspunde, bon blocat pe casă)."""


@dataclass(frozen=True)
class SaleLine:
    """O linie de bon. Pe Tremol: NamePLU`UM, OptionVATClass, Price, Quantity."""
    name: str
    vat_fiscal_code: str     # grupa TVA de pe casă — în aplicație mereu VAT_GROUP ('A')
    unit_price_bani: int
    quantity_milli: int
    line_total_bani: int     # cantitate × preț, rotunjit comercial (vezi database.py)
    unit: str = "buc"        # unitatea de măsură tipărită: 'buc' sau 'kg'


@dataclass(frozen=True)
class Receipt:
    order_id: int
    lines: Tuple[SaleLine, ...]
    total_bani: int
    payment_method: str                  # 'cash' | 'card'
    cash_received_bani: Optional[int]    # la cash: suma primită (≥ total); la card: None
    buyer_cui: str = ""                  # CUI-ul firmei, tipărit pe bon; gol la persoană fizică
    buyer_name: str = ""


@dataclass(frozen=True)
class FiscalResult:
    ok: bool
    doc_number: Optional[int]
    receipt_number: Optional[str]
    message: str
    raw: str
    simulated: bool = False


@dataclass(frozen=True)
class ReportResult:
    ok: bool
    message: str
    z_number: Optional[int] = None       # doar la Z, de pe casă; în simulare îl dă aplicația
    total_bani: Optional[int] = None     # vânzările zilei, cum le vede casa (None în simulare)
    cash_bani: Optional[int] = None
    card_bani: Optional[int] = None
    raw: dict = field(default_factory=dict)
    simulated: bool = False


def mode():
    """'simulate' | 'tremol' | 'none' | 'conflict'"""
    if SIMULATE and TREMOL_PORT:
        return "conflict"
    if SIMULATE:
        return "simulate"
    return "tremol" if TREMOL_PORT else "none"


def mode_problem():
    """Mesajul pentru casier dacă bonurile nu pot fi emise deloc, altfel None."""
    return _MODE_ERRORS.get(mode())


def _device():
    problem = mode_problem()
    if problem:
        raise FiscalError(problem)
    return mode()


_printer = None


def _tremol():
    global _printer
    if _printer is None:
        _printer = tremol.TremolPrinter(
            tremol.serial_transport(TREMOL_PORT, TREMOL_BAUD),
            operator=TREMOL_OPERATOR, password=TREMOL_PASSWORD, card_payment=TREMOL_CARD_PAYMENT,
        )
    return _printer


def _on_tremol(action):
    """Apelul către casa Tremol, cu erorile ei traduse în FiscalError."""
    try:
        return action(_tremol())
    except tremol.DeviceStateError as exc:
        raise FiscalError(str(exc)) from None
    except tremol.TransportError as exc:
        raise FiscalError(
            f"Legătura cu casa de marcat: {exc}. Verificați casa; la reîncercare, "
            "un bon care apucase să se emită este recunoscut și nu se tipărește din nou."
        ) from None
    except ValueError as exc:
        raise FiscalError(f"Comanda nu poate fi trimisă la casă: {exc}") from None


def send_receipt(receipt: Receipt) -> FiscalResult:
    """Emite bonul pe casa configurată. Singurul punct de intrare pentru bonuri."""
    if _device() == "simulate":
        return _simulate(receipt)
    r = _on_tremol(lambda p: p.send_receipt(receipt))
    return FiscalResult(ok=r["ok"], doc_number=r["doc_number"], receipt_number=r["receipt_number"],
                        message=r["message"], raw=r["raw"])


def daily_report(zeroing: bool) -> ReportResult:
    """Raportul Z (zeroing=True — închide ziua fiscală, ireversibil) sau X."""
    if _device() == "simulate":
        log.info("[SIMULARE] Raport %s — NU s-a tipărit pe casă", "Z" if zeroing else "X")
        return ReportResult(ok=True, message="OK [SIMULARE — raportul nu s-a tipărit pe casă]", simulated=True)
    r = _on_tremol(lambda p: p.daily_report(zeroing))
    return ReportResult(ok=r["ok"], message=r["message"], z_number=r.get("z_number"),
                        total_bani=r.get("total_bani"), cash_bani=r.get("cash_bani"),
                        card_bani=r.get("card_bani"), raw=r.get("raw", {}))


def period_report(date_from, date_to) -> ReportResult:
    """Raport scurt din memoria fiscală, pe perioadă (date incluse)."""
    if _device() == "simulate":
        log.info("[SIMULARE] Raport memorie fiscală %s – %s — NU s-a tipărit", date_from, date_to)
        return ReportResult(ok=True, message="OK [SIMULARE — raportul nu s-a tipărit pe casă]", simulated=True)
    r = _on_tremol(lambda p: p.period_report(date_from, date_to))
    return ReportResult(ok=r["ok"], message=r["message"], raw=r.get("raw", {}))


# ─── Mod simulare ─────────────────────────────────────────────────────────────

def _simulate(receipt):
    # Numărul de bon e derivat din comandă: unic, stabil la repornire, și
    # imposibil de confundat cu un bon real
    text = _receipt_text(receipt)
    log.info("[SIMULARE] Bon pentru comanda %d — NU s-a tipărit pe casă:\n%s", receipt.order_id, text)
    return FiscalResult(
        ok=True,
        doc_number=receipt.order_id,
        receipt_number=f"SIM-{receipt.order_id}",
        message="OK [SIMULARE — bonul nu există pe casa de marcat]",
        raw=text,
        simulated=True,
    )


def _lei(bani):
    return f"{bani // 100},{bani % 100:02d}"


def _qty(milli):
    return f"{milli // 1000},{milli % 1000:03d}"


def _receipt_text(receipt):
    """Bonul așa cum l-ar tipări casa, aproximativ — ca să se vadă în log ce s-ar fi emis."""
    rows = [f"CIF client: {receipt.buyer_cui}"] if receipt.buyer_cui else []
    for line in receipt.lines:
        rows.append(
            f"{line.name[:30]:<30} {_qty(line.quantity_milli)} x {_lei(line.unit_price_bani)}"
            f" = {_lei(line.line_total_bani)} {line.vat_fiscal_code}"
        )
    rows.append(f"TOTAL {_lei(receipt.total_bani)}")
    if receipt.payment_method == "cash":
        change = receipt.cash_received_bani - receipt.total_bani
        rows.append(f"NUMERAR {_lei(receipt.cash_received_bani)}  REST {_lei(change)}")
    else:
        rows.append(f"CARD {_lei(receipt.total_bani)}")
    return "\n".join(rows)


if mode() == "simulate":
    log.warning("MOD SIMULARE FISCALĂ (DETOATE_FISCAL_SIMULATE): bonurile NU se tipăresc pe casa de marcat")
elif mode() == "conflict":
    log.error(_MODE_ERRORS["conflict"])
