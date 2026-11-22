"""
Verificarea casei Tremol înainte de prima vânzare reală. Se rulează pe
calculatorul casei, cu casa pornită și conectată, ÎNAINTE de a seta
DETOATE_TREMOL_PORT pentru aplicație. Pașii merg de la inofensiv la real și
nu schimbă nimic pe casă, cu excepția pasului 8, cerut explicit:

  0. fără --port: casa e căutată pe toate porturile COM (și cele USB virtuale),
     la vitezele din protocol — ca FindDevice din SDK-ul Tremol
  1. casa răspunde (04h) și e pregătită (09h)
  2. starea detaliată (20h): memorie fiscală, hârtie, blocare 24 h, bon deschis
  3. modelul (21h și 1Dh 'M'): interfețele casei (RS232, USB, LAN…), cea folosită
     acum, codificarea textului, câte caractere are numele unui articol
  4. cota TVA de pe casă (62h) — grupa A trebuie să fie 21%, singura cotă a aplicației
  5. punctul zecimal (63h) — trebuie „fracții”
  6. tipurile de plată (64h) — 0 e numerarul; cel pentru card → DETOATE_TREMOL_CARD_PAYMENT
  7. ultimul bon (71h), ultimul raport Z (73h), bon deschis acum (72h)
  8. operatorul (6Ah): numele și parola lui de pe casă, comparată cu --password
  9. doar cu --bon: UN bon fiscal real de 0,10 lei, plătit numerar, după confirmare;
     cu --cui RO…, bonul are și CIF-ul cumpărătorului

    python3 tremol_check.py                  (caută casa singur)
    python3 tremol_check.py --port COM3
    python3 tremol_check.py --port COM3 --card-payment 1 --bon
"""
import argparse
import sys
from decimal import Decimal, InvalidOperation

import fiscal
import tremol

BLOCKING_FLAGS = {
    "memorie fiscală doar citire", "imprimantă nepregătită sau supraîncălzită", "oră incorectă", "dată incorectă",
    "defect hardware ceas", "imprimantă nepregătită sau fără hârtie", "blocare după 24 de ore",
    "lipsă modul memorie fiscală", "eroare memorie fiscală", "memorie fiscală plină", "jurnal electronic plin",
}
# Vitezele din PDF 1: 115200 implicit; celelalte doar dacă sunt setate pe casă
SCAN_BAUDS = (115200, 9600, 19200, 38400, 57600)
NAME_CHARS_SENT = 30  # cât trimite adaptorul din numele produsului (tremol._sell_data)

WARNING_FLAGS = {
    "memorie fiscală aproape plină", "jurnal electronic aproape plin", "hârtie pe terminate", "bon fiscal deschis",
    "bon nefiscal deschis", "cădere de curent cu bon deschis", "lipsă certificate", "SIM neactivat",
}


def find_till(out, ports=None, open_port=tremol.serial_transport):
    """
    Casa pe primul port COM care răspunde la 04h, încercând vitezele din protocol:
    (port, baud), sau None. `ports` = [(port, descriere)]; implicit, toate porturile sistemului.
    """
    if ports is None:
        from serial.tools import list_ports  # pyserial

        ports = [(p.device, p.description) for p in list_ports.comports()]
    if not ports:
        out("            niciun port COM — casa e pornită și conectată? (Manager dispozitive → Porturi COM și LPT)")
        return None
    for device, description in ports:
        out(f"            încerc {device} ({description})")
        for baud in SCAN_BAUDS:
            try:
                if tremol.TremolPrinter(open_port(device, baud), timeout=0.5).short_message(0x04) == 0x04:
                    return device, baud
            except tremol.TransportError:
                break  # portul nu se deschide (ocupat, Bluetooth închis) — următorul
    return None


def main(argv=None, open_transport=None, ask=input, out=print, find=find_till):
    parser = argparse.ArgumentParser(description="Verifică o casă Tremol înainte de prima vânzare reală.")
    parser.add_argument("--port", default=fiscal.TREMOL_PORT or None,
                        help="ex. COM3; fără el, casa e căutată pe toate porturile")
    parser.add_argument("--baud", type=int, default=fiscal.TREMOL_BAUD)
    parser.add_argument("--operator", default=fiscal.TREMOL_OPERATOR)
    parser.add_argument("--password", default=fiscal.TREMOL_PASSWORD)
    parser.add_argument("--card-payment", default=fiscal.TREMOL_CARD_PAYMENT, help="tipul de plată pentru card, 1–9")
    parser.add_argument("--bon", action="store_true", help="emite UN bon fiscal real de 0,10 lei")
    parser.add_argument("--cui", default="", help="CIF-ul cumpărătorului pe bonul de test")
    args = parser.parse_args(argv)
    failures = []

    def ok(message):
        out(f"  OK        {message}")

    def warn(message):
        out(f"  ATENȚIE   {message}")

    def fail(message):
        failures.append(message)
        out(f"  EROARE    {message}")

    if open_transport is None:
        if args.port is None:
            out("0. Caut casa pe porturile COM")
            found = find(out)
            if found is None:
                fail("casa nu a fost găsită pe niciun port — verificați cablul, că e pornită și driverul USB")
                return 1
            args.port, args.baud = found
            ok(f"casa e pe {args.port}, la {args.baud} baud")
        open_transport = tremol.serial_transport(args.port, args.baud)
    printer = tremol.TremolPrinter(open_transport, operator=args.operator, password=args.password,
                                   card_payment=args.card_payment)

    try:
        out("1. Legătura")
        if printer.short_message(0x04) != 0x04:
            fail("casa nu răspunde — verificați portul, cablul, viteza (--baud) și că e pornită")
            return 1
        ok("casa răspunde")
        ready = printer.short_message(0x09)
        if ready is None or ready & 0xF0 != 0x40:
            fail(f"răspuns neașteptat la verificarea stării ({ready!r})")
        else:
            problems = [text for bit, text in ((1, "fără hârtie"), (2, "supraîncălzită"), (8, "lipsă afișaj extern"))
                        if ready & bit]
            (fail if problems else ok)("pregătită" if not problems else "casa: " + ", ".join(problems))

        out("2. Starea casei")
        flags = set(printer.status_flags())
        for flag in sorted(flags & BLOCKING_FLAGS):
            fail(flag)
        for flag in sorted(flags & WARNING_FLAGS):
            warn(flag)
        if "memorie fiscală fiscalizată" in flags:
            ok("memorie fiscală fiscalizată")
        else:
            warn("memoria fiscală nu e fiscalizată — bonurile nu au valoare fiscală (casă de test?)")

        out("3. Model")
        ok(";".join(printer.query(tremol.CMD_VERSION)).strip())
        model = printer.model_info()
        if model is None:
            warn("casa nu răspunde la comanda de model (1Dh M) — interfețele nu se pot afișa")
        else:
            ok(f"interfețe: {model.get('interfaces') or '?'} — folosită acum: {model.get('current_interface') or '?'}")
            if "1252" not in model.get("encoding", ""):
                warn(f"codificarea casei e „{model.get('encoding')}”; aplicația trimite text cp1252, fără diacritice")
            name_chars = model.get("article_name_chars", "")
            if name_chars.isdigit() and int(name_chars) < NAME_CHARS_SENT:
                fail(f"casa acceptă nume de articol de {name_chars} caractere; aplicația trimite până la {NAME_CHARS_SENT}")
            elif name_chars.isdigit():
                ok(f"nume de articol: până la {name_chars} caractere acceptate, "
                   f"{model.get('article_name_printable') or '?'} tipărite pe bon")

        out("4. Cota TVA")
        device_rates = dict(zip(tremol.VAT_CLASSES, printer.query(tremol.CMD_READ_VAT_RATES)))
        code, percent = fiscal.VAT_GROUP, Decimal(str(fiscal.VAT_PERCENT)).normalize()
        try:
            on_device = Decimal(device_rates.get(code, "").strip().rstrip("%"))
        except InvalidOperation:
            on_device = None
        if on_device == percent:
            ok(f"grupa {code}: {percent:f}% pe casă, cota aplicației")
        else:
            fail(f"grupa {code}: {on_device}% pe casă, dar aplicația vinde totul cu {percent:f}% — bonurile ar avea TVA greșit")

        out("5. Punct zecimal")
        decimal_point = printer.query(tremol.CMD_READ_DECIMAL_POINT)[0]
        if decimal_point == "2":
            ok("fracții (prețuri cu bani)")
        else:
            fail(f"casa lucrează cu numere întregi ({decimal_point!r}) — aplicația trimite prețuri cu bani")

        out("6. Tipuri de plată")
        names = printer.query(tremol.CMD_READ_PAYMENTS)[:10]
        for number, name in enumerate(names):
            if name.strip():
                role = " ← numerar" if number == 0 else " ← card (--card-payment)" if str(number) == args.card_payment else ""
                out(f"            {number}: {name.strip()}{role}")
        card_name = names[int(args.card_payment)].strip() if int(args.card_payment) < len(names) else ""
        if "CARD" in card_name.upper():
            ok(f"plata cu cardul merge pe tipul {args.card_payment} ({card_name})")
        else:
            warn(f"tipul {args.card_payment} se numește „{card_name}” — verificați DETOATE_TREMOL_CARD_PAYMENT")

        out("7. Numere")
        last, total = printer.query(tremol.CMD_READ_RECEIPT_NUMBERS)[:2]
        ok(f"ultimul bon: {int(last)} (total bonuri: {int(total)})")
        z = printer.query(tremol.CMD_READ_LAST_Z)
        ok(f"ultimul raport Z: nr. {z[1]}, din {z[0]}")
        if printer.query(tremol.CMD_READ_CURRENT_RECEIPT)[0] == "1":
            warn("e un bon deschis acum pe casă — aplicația îl anulează la primul bon, dacă se poate")

        out("8. Operatorul")
        try:
            reply = printer.query(tremol.CMD_READ_OPERATOR, str(args.operator).encode())
        except tremol.TremolError as exc:
            reply = None
            warn(f"casa nu arată operatorul {args.operator} ({exc})")
        if reply is not None and len(reply) < 3:
            warn(f"răspuns neașteptat la citirea operatorului: „{';'.join(reply)}”")
        elif reply is not None:
            name, stored = reply[1].strip(), reply[2]  # număr;nume;parolă — unele case adaugă un „;” la final
            if stored.rstrip() == args.password.rstrip():  # adaptorul completează parola cu spații
                ok(f"operatorul {args.operator} („{name}”): parola „{args.password}” e cea de pe casă")
            elif not stored.strip():
                # gol: operatorul nu are parolă sau casa nu o arată — doar bonul de test lămurește
                warn(f"operatorul {args.operator} („{name}”): casa arată parola goală „{stored}” — fie nu are "
                     f"parolă (încercați --password=), fie casa nu o arată")
            else:
                hint = f" — rulați din nou cu --password {stored}" if stored and stored == stored.strip() else ""
                fail(f"operatorul {args.operator} („{name}”) are pe casă parola „{stored}”, "
                     f"nu „{args.password}”{hint}")

        if args.bon:
            out("9. Bon de test")
            if failures:
                fail("bonul de test nu se emite cât timp verificările de mai sus au erori")
            elif ask("   Se emite UN bon fiscal REAL de 0,10 lei (numerar), înregistrat în memoria fiscală.\n"
                     "   Scrieți DA pentru a continua: ").strip() != "DA":
                warn("bon de test sărit")
            else:
                line = fiscal.SaleLine("TEST CASA", fiscal.VAT_GROUP, 10, 1000, 10, "buc")
                result = printer.send_receipt(fiscal.Receipt(0, (line,), 10, "cash", 10, args.cui.strip(), ""))
                if result["ok"]:
                    ok(f"bon emis, nr. {result['receipt_number']} — verificați-l pe hârtie (preț, TVA {line.vat_fiscal_code}"
                       f"{', CIF ' + args.cui if args.cui else ''})")
                    if not printer.units:
                        warn("casa a refuzat unitatea de măsură (buc/kg) în numele articolului — "
                             "bonurile se tipăresc fără ea")
                else:
                    fail(result["message"])
    except (tremol.TransportError, tremol.TremolError, tremol.DeviceStateError, ValueError) as exc:
        fail(str(exc))

    out("")
    if failures:
        out(f"{len(failures)} probleme — rezolvați-le înainte de a folosi casa din aplicație.")
        return 1
    settings = [f"DETOATE_TREMOL_PORT={args.port or '<port>'}", f"DETOATE_TREMOL_CARD_PAYMENT={args.card_payment}"]
    if args.baud != 115200:
        settings.append(f"DETOATE_TREMOL_BAUD={args.baud}")
    if args.operator != "1":
        settings.append(f"DETOATE_TREMOL_OPERATOR={args.operator}")
    if args.password != "0000":
        settings.append(f"DETOATE_TREMOL_PASSWORD={args.password}")
    out("Casa e pregătită. În config.txt (lângă detoate.exe) treceți:")
    for line in settings:
        out(f"    {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
