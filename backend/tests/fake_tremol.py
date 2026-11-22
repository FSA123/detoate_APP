"""
O casă Tremol falsă, la nivel de octeți, scrisă după protocol_description_RO —
independent de tremol.py (are propria sumă de control), ca o greșeală din
adaptor să nu se reflecte identic aici.

E și transportul (write / read / reset_input_buffer, context manager) și
fabrica lui: TremolPrinter(FakeTremol()) merge direct.

Defecte la cerere, pentru teste:
  refuse[cmd] = "04"    următoarea comandă cmd e refuzată cu acești octeți de stare
  nack_next = n         următoarele n cadre primesc NACK (15h), fără execuție
  busy_next = n         următoarele n cadre primesc RETRY (0Eh), fără execuție
  silent = {cmd}        cmd se execută, dar răspunsul se pierde (o singură dată)
  round_down = True     casa rotunjește liniile în jos (alt total decât aplicația)
  unreachable = True    portul nu se poate deschide
  no_units = True       casa refuză unitatea de măsură („`”) în numele articolului (eroare de sintaxă)
  busy_polls = n        următoarele n întrebări 09h primesc 41h (ocupată, tipărește)
  vanish = {cmd}        cmd se execută, apoi portul dispare (cablul USB cade) până la gone = False
"""
import time
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def _cs(body):
    x = 0
    for b in body:
        x ^= b
    return bytes((0x30 + x // 16, 0x30 + x % 16))


class FakeTremol:
    def __init__(self, password="0000"):
        self.password = password
        self.vat_rates = ["21.00", "11.00", "0.00", "0.00", "0.00", "0.00"]   # A–F
        self.enabled_vat = set("ABC")
        self.payment_names = ["NUMERAR", "CARD", "TICHETE", "CREDIT", "", "", "", "VOUCHER", "", "VALUTA"]
        # Răspunsul la 1Dh 'M', câmpurile din PDF 4; None = model care nu știe comanda
        self.model = ["RO", "1252", "FP", "1601", "15-01-2026", "RS232,USB,LAN", "USB", "", "E", "0", "1", "1",
                      "0", "1", "48", "46", "36", "32", "34", "32", "1", "99999", "10", "6", "8"]
        self.last_receipt = 41
        self.total_receipts = 1200
        self.z_number = 17
        self.daily_vat = dict.fromkeys("ABCDEF", Decimal(0))
        self.daily_payments = [Decimal(0)] * 10
        self.receipt = None          # bonul deschis
        self.printed = []            # bonurile închise
        self.cancelled = 0
        self.reports = []
        self.executed = []           # (seq, cmd, data) pentru fiecare comandă executată
        self.repeats = 0             # cadre primite cu același NBL ca precedentul
        self.refuse = {}
        self.nack_next = 0
        self.busy_next = 0
        self.silent = set()
        self.round_down = False
        self.unreachable = False
        self.no_units = False
        self.busy_polls = 0
        self.ready_queries = 0
        self.vanish = set()
        self.gone = False
        self.connected = False
        self._out = bytearray()
        self._last_seq = None
        self._last_reply = b""

    # ── transport ──

    def __call__(self):
        if self.unreachable or self.gone:
            raise OSError("could not open port COM9")
        return self

    def __enter__(self):
        self.connected = True
        return self

    def __exit__(self, *exc):
        self.connected = False

    def reset_input_buffer(self):
        self._out.clear()

    def read(self, n):
        if self.gone:
            raise OSError("ClearCommError failed (PermissionError(13, 'The device does not recognize the command.'))")
        if not self._out:
            time.sleep(0.005)  # ca timeout-ul portului serial
        chunk = bytes(self._out[:n])
        del self._out[:n]
        return chunk

    def write(self, frame):
        if self.gone:
            raise OSError("WriteFile failed")
        frame = bytes(frame)
        if frame == b"\x04":
            self._out += b"\x04"
            return
        if frame == b"\x09":
            self.ready_queries += 1
            if self.busy_polls:
                self.busy_polls -= 1
                self._out += b"\x41"
            else:
                self._out += b"\x40"
            return
        if frame == b"\x1dM":
            if self.model is not None:
                self._out += b"M" + ";".join(self.model).encode("cp1252") + b"\n"
            return
        if (len(frame) < 7 or frame[0] != 0x02 or frame[-1] != 0x0A
                or frame[1] - 0x20 != len(frame) - 4 or _cs(frame[1:-3]) != frame[-3:-1]):
            self._out += b"\x15"
            return
        if self.nack_next:
            self.nack_next -= 1
            self._out += b"\x15"
            return
        if self.busy_next:
            self.busy_next -= 1
            self._out += b"\x0e"
            return
        seq, cmd, data = frame[2] - 0x20, frame[3], frame[4:-3]
        if seq == self._last_seq:
            # retransmisie: același răspuns, fără a executa din nou (PDF 3.1)
            self.repeats += 1
            self._out += self._last_reply
            return
        if cmd in self.refuse:
            status, reply_data = self.refuse.pop(cmd), None
        else:
            self.executed.append((seq, cmd, data))
            status, reply_data = self._execute(cmd, data)
        if reply_data is None:
            body = bytes((seq + 0x20,)) + status.encode()
            reply = b"\x06" + body + _cs(body) + b"\x0a"
        else:
            body = bytes((len(reply_data) + 3 + 0x20, seq + 0x20, cmd)) + reply_data
            reply = b"\x02" + body + _cs(body) + b"\x0a"
        self._last_seq, self._last_reply = seq, reply
        if cmd in self.silent:
            self.silent.discard(cmd)
            return
        if cmd in self.vanish:
            self.vanish.discard(cmd)
            self.gone = True
            return
        self._out += reply

    # ── comenzi ──

    def _execute(self, cmd, data):
        handler = getattr(self, f"_cmd_{cmd:02x}", None)
        if handler is None:
            return "01", None
        result = handler(data)
        return (result, None) if isinstance(result, str) else ("00", result)

    def _cmd_20(self, data):  # starea detaliată, 7 octeți
        st2 = 0b10 if self.receipt else 0
        return bytes((0x80, 0x80, 0x80 | st2, 0x80 | 0b100000, 0x80, 0x80, 0x80))

    def _cmd_21(self, data):
        return b"ZFP Lab - FP test 1.0"

    def _cmd_30(self, data):
        f = data.split(b";")
        if self.receipt:
            return "42"
        if len(f) < 5 or f[2:4] != [b"0", b"0"]:
            return "04"
        if f[1].decode() != self.password.ljust(4):  # PDF: <OperPass[4]>, exact 4 caractere
            return "92"
        special = f[4] in (b"1", b"3", b"5")
        # operator;parolă;0;0;tip;CUI;destinatar;liber1;liber2;liber3;liber4;adresă (PDF 2.6.4)
        if special and len(f) != 12:
            return "04"
        self.receipt = {
            "operator": f[0].decode(),
            "cui": f[5].decode("cp1252") if special else "",
            "recipient": f[6].decode("cp1252") if special else "",
            "lines": [], "total": Decimal(0), "payment": None,
        }
        return "00"

    def _cmd_31(self, data):
        if not self.receipt or self.receipt["payment"]:
            return "02"
        f = data.split(b";")
        if len(f) != 3 or len(f[0]) != 36:  # PDF 2.6.5: <NamePLU[36]>, câmp fix
            return "04"
        name, sep, unit = f[0].partition(b"`")
        if sep and (self.no_units or len(name) > 30 or len(unit.rstrip()) > 3):
            return "04"
        name, unit = name.rstrip(), unit.strip()
        vat = f[1].decode()
        price, _, qty = f[2].partition(b"*")
        if vat not in self.enabled_vat or len(price) > 10 or len(qty) > 10:
            return "04"
        price, qty = Decimal(price.decode()), Decimal((qty or b"1").decode())
        if qty.as_tuple().exponent < -3:
            return "04"
        total = (price * qty).quantize(CENT, ROUND_DOWN if self.round_down else ROUND_HALF_UP)
        self.receipt["lines"].append({
            "name": name.decode("cp1252"), "unit": unit.decode("cp1252"), "vat": vat,
            "price": f[2].partition(b"*")[0].decode(), "qty": f[2].partition(b"*")[2].decode(), "total": total,
        })
        self.receipt["total"] += total
        return "00"

    def _cmd_33(self, data):
        if not self.receipt:
            return "02"
        return f"{self.receipt['total']:.2f}".encode()

    def _cmd_35(self, data):
        if not self.receipt or not self.receipt["lines"] or self.receipt["payment"]:
            return "02"
        f = data.split(b";")
        if len(f) != 4 or f[1] != b"0" or f[3] != b"1" or not f[0].isdigit():
            return "04"
        amount = self.receipt["total"] if f[2] == b'"' else Decimal(f[2].decode())
        if amount < self.receipt["total"]:
            return "05"
        self.receipt["payment"] = {"type": int(f[0]), "amount": amount, "raw_amount": f[2].decode(),
                                   "change": amount - self.receipt["total"]}
        return "00"

    def _cmd_38(self, data):
        if not self.receipt or not self.receipt["payment"]:
            return "02"
        r, self.receipt = self.receipt, None
        self.last_receipt += 1
        self.total_receipts += 1
        for line in r["lines"]:
            self.daily_vat[line["vat"]] += line["total"]
        self.daily_payments[r["payment"]["type"]] += r["total"]
        self.printed.append(r)
        return "00"

    def _cmd_39(self, data):
        if not self.receipt:
            return "02"
        if self.receipt["payment"]:
            return "07"
        self.receipt = None
        self.cancelled += 1
        return "00"

    def _cmd_62(self, data):
        return ";".join(f"{r}%" for r in self.vat_rates).encode()

    def _cmd_63(self, data):
        return b"2"

    def _cmd_64(self, data):
        return (";".join(self.payment_names) + ";0000.00000").encode()

    def _cmd_6a(self, data):  # număr;nume[20];parolă[4] (PDF: ReadOperatorNamePassword)
        if not data.isdigit() or not 1 <= int(data) <= 20:
            return "04"
        # cu „;” la final, ca pe casa reală (Ver 2.02TRM20-AC)
        return f"{int(data)};{'Operator ' + data.decode():<20};{self.password};".encode()

    def _cmd_6d(self, data):
        return ";".join(f"{v:.2f}" for v in self.daily_vat.values()).encode()

    def _cmd_6e(self, data):
        if data != b"0":
            return "04"
        return ("0;" + ";".join(f"{v:.2f}" for v in self.daily_payments)).encode()

    def _cmd_71(self, data):
        return f"{self.last_receipt:04d};{self.total_receipts:07d}".encode()

    def _cmd_72(self, data):
        r = self.receipt
        if not r:
            return b"0;000;0.00;0.00;0.00;0.00;0.00;0;0;1;1;1;0;0;0.00;0;0.00"
        paid = "0" if r["payment"] else "1"
        return f"1;{len(r['lines']):03d};0.00;0.00;0.00;0.00;0.00;0;0;1;{paid};{paid};0;0;0.00;0;0.00".encode()

    def _cmd_73(self, data):
        return f"19-10-2026;{self.z_number};0".encode()

    def _cmd_7b(self, data):
        f = data.split(b";")
        if len(f) != 2 or not all(len(d) == 6 and d.isdigit() for d in f):
            return "04"
        self.reports.append(("period", f[0].decode(), f[1].decode()))
        return "00"

    def _cmd_7c(self, data):
        if self.receipt:
            return "42"
        if data not in (b"Z", b"X"):
            return "04"
        self.reports.append(data.decode())
        if data == b"Z":
            self.z_number += 1
            self.daily_vat = dict.fromkeys("ABCDEF", Decimal(0))
            self.daily_payments = [Decimal(0)] * 10
        return "00"
