"""
Casa de marcat Tremol (seria ZFP, România), direct pe portul serial — fără
ZFPLabServer. Sursa: protocol_description_RO_2601151250.pdf din SDK-ul Tremol.

Fără Flask și fără bază de date: cadrele sunt funcții pure, iar TremolPrinter
vorbește cu un „transport” — portul serial (serial_transport) sau, în teste,
casa falsă din tests/fake_tremol.py.

Protocolul, pe scurt (capitolele 1 și 3 din PDF):
  cerere   <02h><LEN><NBL><CMD><DATA…><CS><CS><0Ah>
             LEN = numărul de octeți LEN+NBL+CMD+DATA, plus 20h
             NBL = numărul mesajului plus 20h (20h–9Fh); fiecare comandă nouă
                   are alt NBL decât precedenta — același NBL = retransmisie
             CS  = XOR pe LEN…DATA, cele două jumătăți plus 30h (B5h → 3Bh 35h)
  răspuns  ACK   <06h><NBL><STE><STE><CS><CS><0Ah> — STE: eroare casă, eroare comandă
           date  <02h><LEN><NBL><CMD><DATA…><CS><CS><0Ah>
           NACK  15h — cadru stricat, se retrimite
           RETRY 0Eh — casa e ocupată, se retrimite
  Textul e cp1252 (fără ă, ș, ț); prețurile și cantitățile sunt zecimale
  ("12.99", "1.250"), nu bani — conversia se face doar aici.
"""
import logging
import random
import threading
import time
import unicodedata
from decimal import Decimal, InvalidOperation

log = logging.getLogger(__name__)

STX, ETX, ACK, NACK, RETRY = 0x02, 0x0A, 0x06, 0x15, 0x0E
MAX_DATA = 0xFF - 0x20 - 3   # LEN trebuie să încapă într-un octet

# Comenzile folosite, cu numele zfpdef din PDF
CMD_STATUS = 0x20                   # ReadStatus
CMD_VERSION = 0x21                  # ReadVersion
CMD_OPEN_RECEIPT = 0x30             # OpenReceipt / OpenSpecialDocumentReceipt (cu CIF)
CMD_SELL = 0x31                     # SellPLUwithSpecifiedVAT
CMD_SUBTOTAL = 0x33                 # Subtotal
CMD_PAYMENT = 0x35                  # Payment / PayExactSum
CMD_CLOSE_RECEIPT = 0x38            # CloseReceipt
CMD_CANCEL_RECEIPT = 0x39           # CancelReceipt
CMD_READ_VAT_RATES = 0x62           # ReadVATrates
CMD_READ_DECIMAL_POINT = 0x63       # ReadDecimalPoint
CMD_READ_PAYMENTS = 0x64            # ReadPayments
CMD_READ_OPERATOR = 0x6A            # ReadOperatorNamePassword
CMD_READ_AMOUNTS_BY_VAT = 0x6D      # ReadDailyAmountsByVAT
CMD_READ_REGISTERS = 0x6E           # ReadDailyAvailableAmounts (opțiunea '0')
CMD_READ_RECEIPT_NUMBERS = 0x71     # ReadLastAndTotalReceiptNum
CMD_READ_CURRENT_RECEIPT = 0x72     # ReadCurrentReceiptInfo
CMD_READ_LAST_Z = 0x73              # ReadLastDailyReportInfo
CMD_BRIEF_FM_REPORT_BY_DATE = 0x7B  # PrintBriefFMReportByDate
CMD_DAILY_REPORT = 0x7C             # PrintDailyReport

VAT_CLASSES = "ABCDEF"              # F = „Alte taxe”

# „Table Errors” din PDF, 1.2.1: prima cifră e starea casei, a doua a comenzii
FPR_ERRORS = {
    "1": "lipsă hârtie sau defect de imprimantă",
    "2": "depășire registre",
    "3": "ceas defect sau dată/oră greșită",
    "4": "bon fiscal deschis",
    "5": "rest de plată în cont",
    "6": "bon nefiscal deschis",
    "7": "plată înregistrată, dar bonul nu e închis",
    "8": "defect al memoriei fiscale",
    "9": "parolă greșită",
    ":": "lipsă afișaj extern",
    ";": "blocare după 24 de ore — lipsește raportul Z",
    "<": "cap de imprimare supraîncălzit",
    "=": "întrerupere de curent în timpul bonului",
    ">": "jurnal electronic plin",
    "?": "condiții insuficiente",
}
COMMAND_ERRORS = {
    "1": "comandă invalidă",
    "2": "comandă nepermisă în starea curentă",
    "3": "raportul Z zilnic nu este zero",
    "4": "eroare de sintaxă",
    "5": "depășire registre de intrare",
    "6": "registre de intrare zero",
    "7": "tranzacție indisponibilă pentru corecție",
    "8": "sumă insuficientă în casă",
    ":": "fără acces",
    ";": "certificatele nu sunt încărcate",
    "<": "comandă nepermisă — comunicare cu serverul în curs",
}

# Răspunsul la 1Dh 'M' (PDF 4, „Auxiliary GS protocol”), câmp cu câmp, după 'M'
MODEL_FIELDS = [
    "country", "encoding", "device_type", "build", "build_date", "interfaces", "current_interface",
    "battery_support", "battery_supply", "sleep_mode", "sd_journal", "sd_format", "sd_db", "server_exchange",
    "line_chars", "free_text_chars", "article_name_chars", "article_name_printable", "department_name_chars",
    "department_name_printable", "department_first", "article_last", "headers", "fiscal_headers", "footers",
]

# Comanda 20h: 7 octeți de stare, bit cu bit (PDF 2.2.1); None = rezervat
STATUS_FLAGS = [
    ["memorie fiscală doar citire", "cădere de curent cu bon deschis", "imprimantă nepregătită sau supraîncălzită",
     "oră incorectă", "dată incorectă", "RAM resetat", "defect hardware ceas"],
    ["imprimantă nepregătită sau fără hârtie", "depășire registre rapoarte", "blocare după 24 de ore",
     "raport zilnic nenul", "raport articole nenul", "raport operatori nenul", "copie netipărită"],
    ["bon nefiscal deschis", "bon fiscal deschis", "bon de numerar standard", "TVA inclus în bon",
     None, "jurnal electronic aproape plin", "jurnal electronic plin"],
    ["lipsă modul memorie fiscală", "eroare memorie fiscală", "memorie fiscală plină",
     "memorie fiscală aproape plină", "punct zecimal (fracții)", "memorie fiscală fiscalizată",
     "memorie fiscală produsă"],
    ["tăiere automată hârtie", "gestiune afișaj extern", None, "lipsă afișaj extern",
     "sertar: deschidere automată", "logo client în bon", "jumper de service"],
    ["lipsă Sec.IC", "lipsă certificate", None, None, "cardul SD nu răspunde", "card SD greșit", None],
    [None, None, None, None, "hârtie pe terminate", None, "SIM neactivat"],
]


class TremolError(Exception):
    """Casa a răspuns, dar a refuzat comanda (octeții de stare diferiți de "00")."""

    def __init__(self, cmd, status):
        self.cmd = cmd
        self.status = status
        super().__init__(f"{describe_status(status)} (comanda {cmd:02X}h, cod {status})")


class TransportError(Exception):
    """Niciun răspuns valid de la casă (port, cablu, timp expirat) — nu se știe dacă a executat."""


class ProtocolError(TransportError):
    """Răspuns stricat sau neașteptat."""


class DeviceStateError(Exception):
    """Casa e într-o stare din care aplicația nu poate ieși singură (ex. bon deschis cu plată)."""


# ─── Cadre: funcții pure ──────────────────────────────────────────────────────

def checksum(payload):
    """XOR pe toți octeții, apoi fiecare jumătate plus 30h: B5h → 3Bh 35h."""
    x = 0
    for b in payload:
        x ^= b
    return bytes((0x30 + (x >> 4), 0x30 + (x & 0x0F)))


def build_frame(seq, cmd, data=b""):
    """Cadrul unei comenzi. seq = numărul mesajului, 0–127 (NBL = seq + 20h)."""
    if not 0 <= seq <= 0x7F:
        raise ValueError(f"numărul mesajului trebuie să fie 0–127, nu {seq}")
    if len(data) > MAX_DATA:
        raise ValueError(f"datele comenzii au {len(data)} octeți, maximum {MAX_DATA}")
    body = bytes((len(data) + 3 + 0x20, seq + 0x20, cmd)) + data
    return bytes((STX,)) + body + checksum(body) + bytes((ETX,))


def read_response(transport):
    """Exact un răspuns de la casă, după primul octet; b"" dacă nu a venit nimic la timp."""
    first = transport.read(1)
    if not first or first[0] in (NACK, RETRY):
        return first
    if first[0] == ACK:
        return first + transport.read(6)
    if first[0] == STX:
        length = transport.read(1)
        if not length or length[0] < 0x23:
            return first + length
        return first + length + transport.read(length[0] - 0x20 + 2)
    return first


def parse_response(raw):
    """
    Un răspuns complet → dict:
      {"kind": "nack"} / {"kind": "retry"}
      {"kind": "ack",  "seq": n, "status": "00"}
      {"kind": "data", "seq": n, "cmd": c, "data": b"..."}
    """
    if raw in (bytes((NACK,)), bytes((RETRY,))):
        return {"kind": "nack" if raw[0] == NACK else "retry"}
    if len(raw) == 7 and raw[0] == ACK and raw[-1] == ETX:
        if raw[4:6] != checksum(raw[1:4]):
            raise ProtocolError("sumă de control greșită în confirmarea casei")
        return {"kind": "ack", "seq": raw[1] - 0x20, "status": raw[2:4].decode("ascii")}
    if len(raw) >= 7 and raw[0] == STX and raw[-1] == ETX and raw[1] - 0x20 == len(raw) - 4:
        body = raw[1:-3]
        if raw[-3:-1] != checksum(body):
            raise ProtocolError("sumă de control greșită în răspunsul casei")
        return {"kind": "data", "seq": body[1] - 0x20, "cmd": body[2], "data": body[3:]}
    raise ProtocolError(f"răspuns neașteptat sau incomplet de la casă: {raw!r}")


def describe_status(status):
    parts = []
    if status[:1] != "0":
        parts.append("casa: " + FPR_ERRORS.get(status[:1], "eroare necunoscută"))
    if status[1:2] != "0":
        parts.append("comanda: " + COMMAND_ERRORS.get(status[1:2], "eroare necunoscută"))
    return "; ".join(parts) or "OK"


def decode_status(data):
    """Steagurile setate din răspunsul comenzii 20h."""
    flags = []
    for byte, names in zip(data, STATUS_FLAGS):
        flags += [name for bit, name in enumerate(names) if name and byte & (1 << bit)]
    return flags


def fields(data):
    return data.decode("cp1252").split(";")


def encode_text(text, max_len):
    """
    Text pentru casă: fără diacritice (cp1252 nu are ă, ș, ț), fără separatorii
    protocolului (; ` |) și fără caractere de control, cel mult max_len.
    """
    plain = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    plain = "".join(c if c.isprintable() and c not in ";`|" else " " for c in plain)
    return " ".join(plain.split())[:max_len].encode("cp1252", errors="replace")


def format_amount(bani):
    """1299 → "12.99" — prețuri și sume, cum le cere casa."""
    if bani < 0:
        raise ValueError("suma nu poate fi negativă")
    return f"{bani // 100}.{bani % 100:02d}"


def format_quantity(milli):
    """1250 → "1.250" — cantitate cu 3 zecimale."""
    if milli <= 0:
        raise ValueError("cantitatea trebuie să fie pozitivă")
    return f"{milli // 1000}.{milli % 1000:03d}"


def parse_amount(text):
    """Sumă din răspunsul casei ("123.45", " -0.5") → bani, exact."""
    try:
        value = Decimal(text.strip())
    except InvalidOperation:
        raise ProtocolError(f"sumă invalidă de la casă: {text!r}") from None
    bani = value * 100
    if not value.is_finite() or bani != bani.to_integral_value():
        raise ProtocolError(f"sumă invalidă de la casă: {text!r}")
    return int(bani)


def serial_transport(port, baudrate=115200):
    """Fabrica de conexiuni pentru portul serial (sau USB virtual COM): 8N1, ca în PDF 1."""
    def open_port():
        import serial  # pyserial — doar pentru casa reală

        return serial.Serial(port, baudrate=baudrate, bytesize=8, parity="N", stopbits=1,
                             timeout=0.5, write_timeout=2)
    return open_port


# ─── Casa ─────────────────────────────────────────────────────────────────────

class TremolPrinter:
    """
    O casă Tremol. `open_transport()` întoarce o conexiune nouă (context manager
    cu write, read și reset_input_buffer, ca serial.Serial) — deschisă la fiecare
    operație, ca o casă repornită sau un cablu USB mutat să nu blocheze aplicația.

    Rezultatele bonurilor au forma comună a adaptorilor:
      {ok, doc_number, receipt_number, message, raw}
    """

    def __init__(self, open_transport, operator="1", password="0000", card_payment="1",
                 timeout=10.0, report_timeout=180.0):
        if card_payment not in "123456789" or len(card_payment) != 1:
            raise ValueError("tipul de plată pentru card trebuie să fie o cifră 1–9")
        self.open_transport = open_transport
        self.operator = operator
        self.password = password
        self.card_payment = card_payment
        self.timeout = timeout
        self.units = True  # unitatea de măsură în numele articolului; False după ce casa o refuză
        self.report_timeout = report_timeout
        self._lock = threading.Lock()
        # Număr de pornire aleator: primul mesaj după o repornire a aplicației
        # nu trebuie să aibă, din întâmplare, NBL-ul ultimului mesaj dinainte
        self._seq = random.randrange(0x80)
        # Comenzi al căror bon a rămas cu rezultat necunoscut (conexiune pierdută
        # după deschidere): id comandă → ultimul număr de bon dinaintea încercării
        self._uncertain = {}

    # ── Nivel jos ──

    def _command(self, transport, cmd, data=b"", timeout=None):
        """Trimite o comandă; datele răspunsului (b"" la confirmare). TremolError dacă e refuzată."""
        self._seq = (self._seq + 1) % 0x80
        frame = build_frame(self._seq, cmd, data)
        deadline = time.monotonic() + (timeout or self.timeout)
        self._wait_ready(transport, deadline)
        nacks = 0
        transport.reset_input_buffer()
        transport.write(frame)
        while True:
            raw = read_response(transport)
            if not raw:
                if time.monotonic() > deadline:
                    raise TransportError(f"casa nu a răspuns la comanda {cmd:02X}h")
                continue
            reply = parse_response(raw)
            if reply["kind"] == "nack":
                nacks += 1
                if nacks > 3:
                    raise TransportError("casa respinge cadrele — verificați viteza portului (baud)")
                transport.write(frame)  # același NBL: cadrul nu a fost primit
                continue
            if reply["kind"] == "retry":
                if time.monotonic() > deadline:
                    raise TransportError(f"casa a rămas ocupată la comanda {cmd:02X}h")
                time.sleep(0.1)
                transport.write(frame)
                continue
            if reply["seq"] != self._seq:
                continue  # răspuns întârziat la un mesaj mai vechi
            if reply["kind"] == "ack":
                if reply["status"] != "00":
                    raise TremolError(cmd, reply["status"])
                return b""
            if reply["cmd"] != cmd:
                raise ProtocolError(f"răspuns la comanda {reply['cmd']:02X}h în loc de {cmd:02X}h")
            return reply["data"]

    @staticmethod
    def _wait_ready(transport, deadline):
        """
        Ca driverul Tremol: comanda pleacă abia după ce casa a terminat de tipărit
        (09h → 41h cât e ocupată, bit 0). Fără răspuns, comanda pleacă oricum.
        """
        while True:
            transport.reset_input_buffer()
            transport.write(b"\x09")
            reply = transport.read(1)
            if not reply or reply[0] & 0xF1 != 0x41:
                return
            if time.monotonic() > deadline:
                raise TransportError("casa a rămas ocupată (tipărește încă?)")
            time.sleep(0.05)

    def _session(self, work):
        """Rulează `work(transport)` pe o conexiune nouă, cu casa ocupată exclusiv."""
        with self._lock:
            try:
                transport = self.open_transport()
            except OSError as exc:
                raise TransportError(f"portul casei de marcat nu se poate deschide: {exc}") from None
            try:
                with transport:
                    return work(transport)
            except OSError as exc:  # cablul scos sau casa repornită în mijlocul unei comenzi
                raise TransportError(f"legătura cu casa s-a întrerupt ({exc})") from None

    def short_message(self, code):
        """
        Mesajele de un octet din PDF 1.3: 04h → 04h dacă e pornită; 09h → 40h
        dacă e pregătită (bit 0 ocupată, 1 fără hârtie, 2 supraîncălzită,
        3 lipsă afișaj). None dacă nu răspunde.
        """
        def work(t):
            t.reset_input_buffer()
            t.write(bytes((code,)))
            reply = t.read(1)
            return reply[0] if reply else None
        return self._session(work)

    def model_info(self):
        """
        Ce spune casa despre ea (1Dh 'M', PDF 4): interfețele (RS232, USB, LAN…),
        cea folosită acum, codificarea, câte caractere are numele unui articol.
        Dict cu cheile din MODEL_FIELDS, sau None dacă modelul nu răspunde la comandă.
        """
        def work(t):
            t.reset_input_buffer()
            t.write(b"\x1dM")
            reply, deadline = b"", time.monotonic() + 2
            while not reply.endswith(b"\n") and time.monotonic() < deadline:
                reply += t.read(1)
            return reply
        reply = self._session(work)
        if not reply.startswith(b"M") or not reply.endswith(b"\n"):
            return None
        values = reply[1:].rstrip(b"\r\n").decode("cp1252").split(";")
        return dict(zip(MODEL_FIELDS, (v.strip() for v in values)))

    def query(self, cmd, data=b""):
        """O comandă de citire, cu răspunsul ca listă de câmpuri (pentru verificări)."""
        return self._session(lambda t: fields(self._command(t, cmd, data)))

    def status_flags(self):
        return self._session(lambda t: decode_status(self._command(t, CMD_STATUS)))

    # ── Bonul curent ──

    def _open_receipt_info(self, t):
        f = fields(self._command(t, CMD_READ_CURRENT_RECEIPT))
        # InitiatedPayment: '0' = plată începută (sic, PDF 2.8.18)
        return {"open": f[0] == "1", "payment_started": len(f) > 10 and f[10] == "0"}

    def _last_receipt_numbers(self, t):
        last, total = fields(self._command(t, CMD_READ_RECEIPT_NUMBERS))[:2]
        return int(last), int(total)

    def _cancel_open_receipt(self, t, info):
        """Un bon rămas deschis (cădere de curent, conexiune pierdută) — anulat, dacă se mai poate."""
        try:
            self._command(t, CMD_CANCEL_RECEIPT)
        except TremolError:
            what = "cu plata începută" if info["payment_started"] else "care nu se poate anula"
            raise DeviceStateError(
                f"Pe casă a rămas un bon deschis {what}. Finalizați-l sau anulați-l de pe casă, apoi reîncercați."
            ) from None
        log.warning("Bon rămas deschis pe casa Tremol — anulat înainte de bonul nou")

    def _cancel_if_open(self, t):
        """După un refuz: anulează bonul, dacă apucase să se deschidă."""
        try:
            if self._open_receipt_info(t)["open"]:
                self._command(t, CMD_CANCEL_RECEIPT)
        except (TremolError, TransportError):
            log.exception("Bonul nu s-a putut anula pe casa Tremol")

    def _open_data(self, receipt):
        # Parola are mereu 4 caractere (PDF: <OperPass[4]>): completată cu spații, deci „fără parolă” = 4 spații
        base = f"{self.operator};{self.password.ljust(4)};0;0;".encode()
        if not receipt.buyer_cui:
            return base + b"0"  # bon normal, tipărire pas cu pas
        # „Special customer document” — bonul cu CIF-ul cumpărătorului
        return (base + b"1;" + encode_text(receipt.buyer_cui, 15) + b";"
                + encode_text(receipt.buyer_name, 30) + b";;;;;")

    @staticmethod
    def _sell_data(line, with_unit=True):
        if line.vat_fiscal_code not in VAT_CLASSES or len(line.vat_fiscal_code) != 1:
            raise ValueError(f"grupa TVA „{line.vat_fiscal_code}” nu există pe casa Tremol")
        # NamePLU are fix 36 caractere (PDF 2.6.5): 30 denumirea, „`”, 3 unitatea, 2 spații
        name = encode_text(line.name, 30)
        if with_unit:
            name_plu = name.ljust(30) + b"`" + encode_text(line.unit, 3).ljust(3) + b"  "
        else:
            name_plu = name.ljust(36)
        return (name_plu + b";" + line.vat_fiscal_code.encode() + b";"
                + format_amount(line.unit_price_bani).encode() + b"*" + format_quantity(line.quantity_milli).encode())

    def _sell(self, t, line):
        """
        O linie de bon. Dacă linia cu unitatea de măsură e refuzată doar ca eroare
        de sintaxă (cod 04: casa nu a înregistrat-o) și trece fără unitate, liniile
        merg de atunci fără unitate.
        """
        if self.units:
            try:
                self._command(t, CMD_SELL, self._sell_data(line))
                return
            except TremolError as exc:
                if exc.status != "04":
                    raise
            self._command(t, CMD_SELL, self._sell_data(line, with_unit=False))
            log.warning("Casa refuză unitatea de măsură în numele articolului — liniile merg fără ea")
            self.units = False
            return
        self._command(t, CMD_SELL, self._sell_data(line, with_unit=False))

    def send_receipt(self, receipt):
        """
        Bonul complet: deschidere → linii → subtotal verificat → plată → închidere
        → numărul bonului. Până la plată, orice refuz anulează bonul pe casă și
        întoarce ok=False; comanda din aplicație rămâne neplătită.
        """
        for line in receipt.lines:
            self._sell_data(line)  # ValueError înainte de orice tipărire
        return self._session(lambda t: self._receipt(t, receipt))

    def _receipt(self, t, receipt):
        info = self._open_receipt_info(t)
        if receipt.order_id in self._uncertain:
            # Încercarea precedentă a pierdut legătura cu casa: dacă bonul a
            # apucat să se emită, nu se mai tipărește încă o dată
            before = self._uncertain.pop(receipt.order_id)
            last, total = self._last_receipt_numbers(t)
            if not info["open"] and last != before:
                return self._result(True, last, total, "Bonul fusese deja emis la încercarea precedentă")
        if info["open"]:
            self._cancel_open_receipt(t, info)

        before, _ = self._last_receipt_numbers(t)
        self._uncertain[receipt.order_id] = before
        try:
            self._command(t, CMD_OPEN_RECEIPT, self._open_data(receipt))
            for line in receipt.lines:
                self._sell(t, line)
            subtotal = parse_amount(fields(self._command(t, CMD_SUBTOTAL, b"0;0"))[0])
            if subtotal != receipt.total_bani:
                self._command(t, CMD_CANCEL_RECEIPT)
                del self._uncertain[receipt.order_id]
                return self._result(False, message=(
                    f"Totalul calculat de casă ({format_amount(subtotal)}) diferă de cel din aplicație "
                    f"({format_amount(receipt.total_bani)}) — bonul a fost anulat pe casă"))
            if receipt.payment_method == "cash":
                payment = f"0;0;{format_amount(receipt.cash_received_bani)};1"
            else:
                payment = f'{self.card_payment};0;";1'  # suma exactă
            self._command(t, CMD_PAYMENT, payment.encode())
        except TremolError as exc:
            # Refuzat înainte să se încheie plata: bonul se anulează, nimic nu s-a încasat
            self._cancel_if_open(t)
            del self._uncertain[receipt.order_id]
            return self._result(False, message=f"Casa a refuzat bonul: {exc}")

        try:
            self._command(t, CMD_CLOSE_RECEIPT)
        except TremolError as exc:
            del self._uncertain[receipt.order_id]
            return self._result(False, message=(
                f"Plata e înregistrată pe casă, dar bonul nu s-a închis: {exc}. "
                "Rezolvați pe casă înainte de a reîncerca."))
        del self._uncertain[receipt.order_id]
        try:
            last, total = self._last_receipt_numbers(t)
        except (TremolError, TransportError):
            log.exception("Bon emis, dar numărul lui nu s-a putut citi de pe casă")
            return self._result(True, message="Bon emis; numărul bonului nu s-a putut citi de pe casă")
        return self._result(True, last, total)

    @staticmethod
    def _result(ok, receipt_number=None, doc_number=None, message="OK"):
        return {
            "ok": ok,
            "doc_number": doc_number,
            "receipt_number": None if receipt_number is None else str(receipt_number),
            "message": message,
            "raw": "",
        }

    # ── Rapoarte ──

    def daily_report(self, zeroing):
        """
        Raportul Z (zeroing=True, închide ziua fiscală) sau X. Registrele zilei
        se citesc înainte, fiindcă Z le golește.
        → {ok, z_number, total_bani, cash_bani, card_bani, message, raw}
        """
        return self._session(lambda t: self._daily_report(t, zeroing))

    def _daily_report(self, t, zeroing):
        if self._open_receipt_info(t)["open"]:
            return {"ok": False, "message": "Pe casă e un bon deschis — finalizați-l înainte de raport", "raw": {}}
        by_payment = fields(self._command(t, CMD_READ_REGISTERS, b"0"))
        by_vat = fields(self._command(t, CMD_READ_AMOUNTS_BY_VAT))
        raw = {"payments": by_payment, "vat": by_vat}
        try:
            totals = {
                "total_bani": sum(parse_amount(v) for v in by_vat if v.strip()),
                "cash_bani": parse_amount(by_payment[1]),
                "card_bani": parse_amount(by_payment[1 + int(self.card_payment)]),
            }
        except (ProtocolError, IndexError):
            log.exception("Registrele casei nu s-au putut interpreta — raportul se emite oricum")
            totals = {"total_bani": None, "cash_bani": None, "card_bani": None}
        try:
            self._command(t, CMD_DAILY_REPORT, b"Z" if zeroing else b"X", timeout=self.report_timeout)
        except TremolError as exc:
            return {"ok": False, "message": f"Casa a refuzat raportul: {exc}", "raw": raw}
        z_number = None
        if zeroing:
            try:  # raportul Z s-a emis deja — un număr necitit nu îl face eșuat
                last_z = fields(self._command(t, CMD_READ_LAST_Z))
                raw["last_z"] = last_z
                z_number = int(last_z[1])
            except (TremolError, TransportError, IndexError, ValueError):
                log.exception("Raport Z emis, dar numărul lui nu s-a putut citi de pe casă")
        return {"ok": True, "z_number": z_number, **totals, "message": "OK", "raw": raw}

    def period_report(self, date_from, date_to):
        """Raport scurt din memoria fiscală, între două date (inclusiv)."""
        data = f"{date_from:%d%m%y};{date_to:%d%m%y}".encode()

        def work(t):
            try:
                self._command(t, CMD_BRIEF_FM_REPORT_BY_DATE, data, timeout=self.report_timeout)
            except TremolError as exc:
                return {"ok": False, "message": f"Casa a refuzat raportul: {exc}", "raw": {}}
            return {"ok": True, "message": "OK", "raw": {}}
        return self._session(work)
