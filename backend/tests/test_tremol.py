import unittest
from datetime import date

import fiscal
import tremol
from tests.fake_tremol import FakeTremol


def line(name, vat, price, qty, total, unit="buc"):
    return fiscal.SaleLine(name, vat, price, qty, total, unit)


def receipt(*lines, method="cash", cash=None, cui="", name="", order_id=1):
    lines = lines or (line("Pâine", "B", 450, 2000, 900),)
    total = sum(l.line_total_bani for l in lines)
    if method == "cash" and cash is None:
        cash = total
    return fiscal.Receipt(order_id, tuple(lines), total, method, cash if method == "cash" else None, cui, name)


class FrameTest(unittest.TestCase):
    def test_checksum_matches_the_protocol_example(self):
        # PDF 1.1: „B5h -> 3Bh 35h”
        self.assertEqual(tremol.checksum(bytes([0xB5])), b"\x3b\x35")
        self.assertEqual(tremol.checksum(bytes([0xF0, 0x45])), b"\x3b\x35")  # F0h XOR 45h = B5h
        self.assertEqual(tremol.checksum(b""), b"00")

    def test_build_frame(self):
        # status (20h), mesajul 0: LEN = 3 + 20h = 23h, NBL = 20h; XOR(23h, 20h, 20h) = 23h → "23"
        self.assertEqual(tremol.build_frame(0, 0x20), b"\x02\x23\x20\x20\x32\x33\x0a")
        data = b"Paine`buc;B;4.50*2.000"
        frame = tremol.build_frame(5, 0x31, data)
        self.assertEqual((frame[1], frame[2], frame[3]), (len(data) + 3 + 0x20, 0x25, 0x31))
        self.assertEqual(frame[4:-3], data)
        self.assertEqual(frame[-3:-1], tremol.checksum(frame[1:-3]))

    def test_build_frame_limits(self):
        with self.assertRaises(ValueError):
            tremol.build_frame(128, 0x20)
        with self.assertRaises(ValueError):
            tremol.build_frame(0, 0x31, b"x" * (tremol.MAX_DATA + 1))
        self.assertEqual(tremol.build_frame(0x7F, 0x20, b"x" * tremol.MAX_DATA)[1], 0xFF)

    def test_parse_responses(self):
        ack = b"\x06\x25" + b"00" + tremol.checksum(b"\x2500") + b"\x0a"
        self.assertEqual(tremol.parse_response(ack), {"kind": "ack", "seq": 5, "status": "00"})
        data = tremol.build_frame(9, 0x71, b"0042;0001201")
        self.assertEqual(tremol.parse_response(data), {"kind": "data", "seq": 9, "cmd": 0x71, "data": b"0042;0001201"})
        self.assertEqual(tremol.parse_response(b"\x15"), {"kind": "nack"})
        self.assertEqual(tremol.parse_response(b"\x0e"), {"kind": "retry"})

    def test_corrupt_responses_are_rejected(self):
        good = tremol.build_frame(9, 0x71, b"0042;0001201")
        for raw in (good[:-1], good[:-3] + b"00" + b"\x0a", b"\x06\x25" + b"00" + b"99\x0a", b"\x07", b""):
            with self.subTest(raw=raw), self.assertRaises(tremol.ProtocolError):
                tremol.parse_response(raw)

    def test_encode_text(self):
        self.assertEqual(tremol.encode_text("Șuncă țărănească; „bio”", 40), "Sunca taraneasca „bio”".encode("cp1252"))
        self.assertEqual(tremol.encode_text("Ţelină`kg|x\n", 40), b"Telina kg x")
        self.assertEqual(tremol.encode_text("Roșii cherry românești extra-dulci", 30), b"Rosii cherry romanesti extra-d")
        self.assertEqual(tremol.encode_text("Ceai 日本", 30), b"Ceai ??")

    def test_amounts(self):
        self.assertEqual([tremol.format_amount(b) for b in (1299, 5, 0, 99_999_999)], ["12.99", "0.05", "0.00", "999999.99"])
        self.assertEqual([tremol.format_quantity(m) for m in (1250, 3000, 1)], ["1.250", "3.000", "0.001"])
        self.assertEqual([tremol.parse_amount(t) for t in ("123.45", " -0.5", "7", "0.10")], [12345, -50, 700, 10])
        for text in ("", "abc", "1.234", "NaN", "Infinity"):
            with self.subTest(text=text), self.assertRaises(tremol.ProtocolError):
                tremol.parse_amount(text)
        with self.assertRaises(ValueError):
            tremol.format_amount(-1)

    def test_status_descriptions(self):
        self.assertEqual(tremol.describe_status("00"), "OK")
        self.assertEqual(tremol.describe_status("14"), "casa: lipsă hârtie sau defect de imprimantă; comanda: eroare de sintaxă")
        self.assertEqual(tremol.describe_status("3;"), "casa: ceas defect sau dată/oră greșită; comanda: certificatele nu sunt încărcate")
        self.assertEqual(tremol.decode_status(bytes([0b1, 0, 0b10, 0b100000, 0, 0, 0])),
                         ["memorie fiscală doar citire", "bon fiscal deschis", "memorie fiscală fiscalizată"])


class PrinterTestCase(unittest.TestCase):
    def setUp(self):
        self.device = FakeTremol()
        self.printer = tremol.TremolPrinter(self.device, timeout=0.3)

    def commands(self):
        return [cmd for _, cmd, _ in self.device.executed]


class ReceiptTest(PrinterTestCase):
    def test_cash_receipt(self):
        r = self.printer.send_receipt(receipt(
            line("Roșii cherry", "B", 1299, 1250, 1624, unit="kg"),
            line("Ciocolată cu lapte", "A", 699, 3000, 2097),
            cash=5000,
        ))
        self.assertEqual(r, {"ok": True, "doc_number": 1201, "receipt_number": "42", "message": "OK", "raw": ""})
        printed = self.device.printed[0]
        self.assertEqual([(l["name"], l["unit"], l["vat"], l["price"], l["qty"]) for l in printed["lines"]], [
            ("Rosii cherry", "kg", "B", "12.99", "1.250"),
            ("Ciocolata cu lapte", "buc", "A", "6.99", "3.000"),
        ])
        self.assertEqual((printed["payment"]["type"], printed["payment"]["raw_amount"]), (0, "50.00"))
        self.assertEqual(str(printed["payment"]["change"]), "12.79")
        self.assertEqual((printed["operator"], printed["cui"]), ("1", ""))
        self.assertEqual(self.commands(), [0x72, 0x71, 0x30, 0x31, 0x31, 0x33, 0x35, 0x38, 0x71])
        self.assertFalse(self.device.connected)  # conexiunea se închide după bon

    def test_name_is_a_fixed_36_character_field(self):
        self.printer.send_receipt(receipt(line("Roșii cherry", "B", 1299, 1250, 1624, unit="kg")))
        sell = [d for _, cmd, d in self.device.executed if cmd == 0x31]
        self.assertEqual(sell, [b"Rosii cherry" + b" " * 18 + b"`kg   " + b";B;12.99*1.250"])
        self.assertEqual(len(sell[0].split(b";")[0]), 36)

    def test_till_without_units_gets_the_name_only(self):
        self.device.no_units = True
        with self.assertLogs("tremol", "WARNING"):
            r = self.printer.send_receipt(receipt(line("Roșii", "B", 1299, 1250, 1624, unit="kg"),
                                                  line("Lapte", "A", 799, 1000, 799), order_id=1))
        self.assertTrue(r["ok"], r)
        self.assertEqual([(l["name"], l["unit"]) for l in self.device.printed[0]["lines"]], [("Rosii", ""), ("Lapte", "")])
        self.assertFalse(self.printer.units)
        self.assertTrue(self.printer.send_receipt(receipt(order_id=2))["ok"])  # nu mai încearcă unitatea
        with_unit = [d for _, cmd, d in self.device.executed if cmd == 0x31 and b"`" in d]
        self.assertEqual(len(with_unit), 1)
        self.assertEqual(len(self.device.printed), 2)

    def test_every_command_gets_a_new_message_number(self):
        for order_id in (1, 2, 3):
            self.printer.send_receipt(receipt(order_id=order_id))
        seqs = [seq for seq, _, _ in self.device.executed]
        self.assertTrue(all(a != b for a, b in zip(seqs, seqs[1:])))
        self.assertTrue(all(0 <= s <= 0x7F for s in seqs))
        self.assertEqual(self.device.repeats, 0)

    def test_card_pays_exact_sum_with_programmed_payment_type(self):
        printer = tremol.TremolPrinter(self.device, card_payment="7", timeout=0.3)
        self.assertTrue(printer.send_receipt(receipt(method="card"))["ok"])
        payment = self.device.printed[0]["payment"]
        self.assertEqual((payment["type"], payment["raw_amount"]), (7, '"'))

    def test_company_receipt_carries_the_cui(self):
        self.printer.send_receipt(receipt(cui="RO14080700", name="SC Legume și Fructe din Grădina Bunicii SRL"))
        printed = self.device.printed[0]
        self.assertEqual((printed["cui"], printed["recipient"]), ("RO14080700", "SC Legume si Fructe din Gradin"))

    def test_refused_line_cancels_the_receipt(self):
        # grupa D nu e activă pe casa falsă: refuzată și cu, și fără unitate de măsură
        r = self.printer.send_receipt(receipt(line("Pâine", "D", 450, 1000, 450)))
        self.assertFalse(r["ok"])
        self.assertIn("eroare de sintaxă", r["message"])
        self.assertEqual((self.device.printed, self.device.cancelled, self.device.receipt), ([], 1, None))
        self.assertTrue(self.printer.units)  # nu unitatea era problema

    def test_other_refusals_of_a_line_are_not_retried(self):
        self.device.refuse[0x31] = "14"  # fără hârtie
        r = self.printer.send_receipt(receipt())
        self.assertFalse(r["ok"])
        self.assertEqual(len([cmd for _, cmd, _ in self.device.executed if cmd == 0x31]), 0)
        self.assertTrue(self.printer.units)

    def test_subtotal_mismatch_cancels_before_payment(self):
        # 2,5 kg × 1,01 = 2,525: aplicația rotunjește la 2,53; o casă care rotunjește în jos dă 2,52
        self.device.round_down = True
        r = self.printer.send_receipt(receipt(line("Cartofi", "B", 101, 2500, 253, unit="kg")))
        self.assertFalse(r["ok"])
        self.assertIn("Totalul calculat de casă (2.52) diferă de cel din aplicație (2.53)", r["message"])
        self.assertEqual((self.device.printed, self.device.cancelled), ([], 1))
        self.assertNotIn(0x35, self.commands())

    def test_refused_payment_cancels(self):
        self.device.refuse[0x35] = "05"
        self.assertFalse(self.printer.send_receipt(receipt())["ok"])
        self.assertEqual((self.device.printed, self.device.cancelled), ([], 1))

    def test_refused_close_after_payment_is_not_cancelled(self):
        self.device.refuse[0x38] = "70"
        r = self.printer.send_receipt(receipt())
        self.assertFalse(r["ok"])
        self.assertIn("Plata e înregistrată pe casă", r["message"])
        self.assertEqual(self.device.cancelled, 0)
        self.assertNotIn(0x39, self.commands())

    def test_wrong_password(self):
        printer = tremol.TremolPrinter(self.device, password="1234", timeout=0.3)
        r = printer.send_receipt(receipt())
        self.assertFalse(r["ok"])
        self.assertIn("parolă greșită", r["message"])

    def test_password_is_always_sent_as_four_characters(self):
        for password, sent in (("", b"1;    ;0;0;0"), ("0", b"1;0   ;0;0;0"), ("0000", b"1;0000;0;0;0")):
            self.device.password = password
            printer = tremol.TremolPrinter(self.device, password=password, timeout=0.3)
            self.assertTrue(printer.send_receipt(receipt())["ok"], password)
            self.assertEqual([d for _, cmd, d in self.device.executed if cmd == 0x30][-1], sent)

    def test_invalid_vat_class_is_rejected_before_talking_to_the_till(self):
        with self.assertRaises(ValueError):
            self.printer.send_receipt(receipt(line("X", "Z", 100, 1000, 100)))
        self.assertEqual(self.device.executed, [])

    def test_nack_is_retransmitted_with_the_same_number(self):
        self.device.nack_next = 2
        self.assertTrue(self.printer.send_receipt(receipt())["ok"])
        self.assertEqual((len(self.device.printed), self.device.repeats), (1, 0))

    def test_busy_till_is_retried(self):
        self.device.busy_next = 3
        self.assertTrue(self.printer.send_receipt(receipt())["ok"])

    def test_leftover_open_receipt_is_cancelled_first(self):
        self.device.receipt = {"operator": "1", "cui": "", "recipient": "", "lines": [], "total": 0, "payment": None}
        with self.assertLogs("tremol", "WARNING"):
            self.assertTrue(self.printer.send_receipt(receipt())["ok"])
        self.assertEqual((self.device.cancelled, len(self.device.printed)), (1, 1))

    def test_leftover_receipt_with_payment_blocks(self):
        self.device.receipt = {"operator": "1", "cui": "", "recipient": "", "lines": [{}], "total": 0,
                               "payment": {"type": 0}}
        with self.assertRaises(tremol.DeviceStateError) as ctx:
            self.printer.send_receipt(receipt())
        self.assertIn("plata începută", str(ctx.exception))
        self.assertEqual(self.device.printed, [])

    def test_lost_reply_after_close_is_not_printed_twice(self):
        self.device.silent = {0x38}  # bonul se emite, dar confirmarea se pierde
        with self.assertRaises(tremol.TransportError):
            self.printer.send_receipt(receipt(order_id=7))
        self.assertEqual(len(self.device.printed), 1)
        r = self.printer.send_receipt(receipt(order_id=7))  # casierul reîncearcă
        self.assertEqual((r["ok"], r["receipt_number"]), (True, "42"))
        self.assertIn("deja emis", r["message"])
        self.assertEqual(len(self.device.printed), 1)

    def test_lost_connection_before_payment_reprints_once(self):
        self.device.silent = {0x33}
        with self.assertRaises(tremol.TransportError):
            self.printer.send_receipt(receipt(order_id=7))
        self.assertIsNotNone(self.device.receipt)  # rămas deschis pe casă
        with self.assertLogs("tremol", "WARNING"):
            self.assertTrue(self.printer.send_receipt(receipt(order_id=7))["ok"])
        self.assertEqual((len(self.device.printed), self.device.cancelled), (1, 1))

    def test_other_order_is_not_mistaken_for_the_uncertain_one(self):
        self.device.silent = {0x38}
        with self.assertRaises(tremol.TransportError):
            self.printer.send_receipt(receipt(order_id=7))
        self.assertTrue(self.printer.send_receipt(receipt(order_id=8))["ok"])
        self.assertEqual(len(self.device.printed), 2)

    def test_unreachable_port(self):
        self.device.unreachable = True
        with self.assertRaises(tremol.TransportError) as ctx:
            self.printer.send_receipt(receipt())
        self.assertIn("portul casei de marcat nu se poate deschide", str(ctx.exception))

    def test_silent_till_times_out(self):
        self.device.silent = {0x72}
        with self.assertRaises(tremol.TransportError):
            self.printer.send_receipt(receipt())

    def test_usb_drop_mid_receipt_is_a_transport_error_and_the_retry_prints_once(self):
        # ca pe casa reală: bonul s-a deschis, apoi portul USB a dispărut la prima linie
        self.device.vanish = {0x31}
        with self.assertRaises(tremol.TransportError) as ctx:
            self.printer.send_receipt(receipt(order_id=7))
        self.assertIn("legătura cu casa s-a întrerupt", str(ctx.exception))
        self.assertIsNotNone(self.device.receipt)  # rămas deschis pe casă
        self.device.gone = False  # cablul e din nou conectat
        with self.assertLogs("tremol", "WARNING"):
            self.assertTrue(self.printer.send_receipt(receipt(order_id=7))["ok"])
        self.assertEqual((len(self.device.printed), self.device.cancelled), (1, 1))

    def test_waits_while_the_till_is_printing(self):
        self.device.busy_polls = 5
        self.assertTrue(self.printer.send_receipt(receipt())["ok"])
        self.assertEqual(self.device.busy_polls, 0)
        self.assertEqual(len(self.device.printed), 1)

    def test_till_that_stays_busy_times_out(self):
        self.device.busy_polls = 10**6
        printer = tremol.TremolPrinter(self.device, timeout=0.3)
        with self.assertRaises(tremol.TransportError) as ctx:
            printer.send_receipt(receipt())
        self.assertIn("ocupată", str(ctx.exception))
        self.assertEqual(self.device.executed, [])


class ReportTest(PrinterTestCase):
    def test_z_report_reads_totals_then_zeroes(self):
        self.printer.send_receipt(receipt(line("Pâine", "B", 450, 2000, 900), method="cash", cash=1000, order_id=1))
        self.printer.send_receipt(receipt(line("Lapte", "B", 799, 1000, 799), method="card", order_id=2))
        r = self.printer.daily_report(zeroing=True)
        self.assertEqual((r["ok"], r["z_number"], r["total_bani"], r["cash_bani"], r["card_bani"]), (True, 18, 1699, 900, 799))
        self.assertEqual(self.device.reports, ["Z"])
        self.assertEqual(self.printer.daily_report(zeroing=False)["total_bani"], 0)  # zerorat

    def test_x_report_does_not_zero(self):
        self.printer.send_receipt(receipt())
        r = self.printer.daily_report(zeroing=False)
        self.assertEqual((r["ok"], r["z_number"], r["total_bani"]), (True, None, 900))
        self.assertEqual(self.printer.daily_report(zeroing=False)["total_bani"], 900)

    def test_report_refused_with_open_receipt(self):
        self.device.receipt = {"operator": "1", "cui": "", "recipient": "", "lines": [], "total": 0, "payment": None}
        r = self.printer.daily_report(zeroing=True)
        self.assertFalse(r["ok"])
        self.assertEqual(self.device.reports, [])

    def test_period_report_dates(self):
        self.assertTrue(self.printer.period_report(date(2026, 10, 1), date(2026, 10, 19))["ok"])
        self.assertEqual(self.device.reports, [("period", "011026", "191026")])

    def test_reading_commands(self):
        self.assertEqual(self.printer.short_message(0x04), 0x04)
        self.assertEqual(self.printer.short_message(0x09), 0x40)
        self.assertEqual(self.printer.query(tremol.CMD_READ_VAT_RATES)[:3], ["21.00%", "11.00%", "0.00%"])
        self.assertIn("memorie fiscală fiscalizată", self.printer.status_flags())


if __name__ == "__main__":
    unittest.main()
