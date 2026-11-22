import unittest
from unittest import mock

import tremol
import tremol_check
from tests.fake_tremol import FakeTremol
from tests.helpers import ApiTestCase


class TremolCheckTest(ApiTestCase):
    """Scriptul de verificare, rulat pe casa falsă."""

    def setUp(self):
        super().setUp()
        self.device = FakeTremol()
        self.lines = []

    def run_check(self, *argv, answer="nu"):
        code = tremol_check.main(list(argv), open_transport=self.device, ask=lambda _: answer, out=self.lines.append)
        return code, "\n".join(self.lines)

    def test_healthy_till_passes_without_printing(self):
        code, output = self.run_check()
        self.assertEqual(code, 0, output)
        for expected in ("OK        casa răspunde", "OK        grupa A: 21% pe casă, cota aplicației", "OK        fracții",
                         "1: CARD ← card", "OK        ultimul bon: 41", "OK        ultimul raport Z: nr. 17",
                         "Casa e pregătită"):
            self.assertIn(expected, output)
        self.assertEqual(self.device.printed, [])
        self.assertNotIn(0x30, [cmd for _, cmd, _ in self.device.executed])  # nimic deschis pe casă

    def test_vat_mismatch_fails(self):
        self.device.vat_rates[0] = "19.00"
        code, output = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("grupa A: 19.00% pe casă, dar aplicația vinde totul cu 21%", output)

    def test_other_vat_groups_on_the_till_do_not_matter(self):
        self.device.vat_rates[1] = "9.00"   # grupa B nu e folosită de aplicație
        code, output = self.run_check()
        self.assertEqual(code, 0, output)
        self.assertNotIn("grupa B", output)

    def test_wrong_card_payment_type_warns(self):
        code, output = self.run_check("--card-payment", "2")
        self.assertEqual(code, 0)
        self.assertIn("tipul 2 se numește „TICHETE”", output)

    def test_test_receipt_needs_typed_confirmation(self):
        code, output = self.run_check("--bon", answer="da")
        self.assertIn("bon de test sărit", output)
        self.assertEqual(self.device.printed, [])
        code, output = self.run_check("--bon", "--cui", "RO14080700", answer="DA")
        self.assertEqual(code, 0, output)
        self.assertIn("bon emis, nr. 42", output)
        printed = self.device.printed[0]
        self.assertEqual((printed["lines"][0]["price"], printed["lines"][0]["vat"], printed["cui"]), ("0.10", "A", "RO14080700"))

    def test_till_that_refuses_units_still_prints_the_test_receipt(self):
        self.device.no_units = True
        with self.assertLogs("tremol", "WARNING"):
            code, output = self.run_check("--bon", answer="DA")
        self.assertEqual(code, 0, output)
        self.assertIn("bon emis", output)
        self.assertIn("casa a refuzat unitatea de măsură (buc/kg)", output)

    def test_operator_password_is_read_from_the_till(self):
        code, output = self.run_check()
        self.assertIn("OK        operatorul 1 („Operator 1”): parola „0000” e cea de pe casă", output)
        self.assertNotIn("DETOATE_TREMOL_PASSWORD", output)  # cea implicită: nimic de trecut în config.txt

    def test_wrong_password_fails_before_the_test_receipt(self):
        self.device.password = "1234"
        code, output = self.run_check("--password", "0", "--bon", answer="DA")
        self.assertEqual(code, 1)
        self.assertIn("operatorul 1 („Operator 1”) are pe casă parola „1234”, nu „0” — rulați din nou cu --password 1234",
                      output)
        self.assertNotIn(0x30, [cmd for _, cmd, _ in self.device.executed])  # niciun bon încercat
        self.lines.clear()
        code, output = self.run_check("--operator", "2", "--password", "1234", "--bon", answer="DA")
        self.assertEqual(code, 0, output)
        self.assertIn("bon emis", output)
        self.assertIn("DETOATE_TREMOL_OPERATOR=2", output)
        self.assertIn("DETOATE_TREMOL_PASSWORD=1234", output)
        self.assertEqual(self.device.printed[0]["operator"], "2")

    def test_blank_password_on_the_till_does_not_block_the_test_receipt(self):
        self.device.password = ""
        code, output = self.run_check("--bon", answer="DA")  # parola implicită 0000: refuzată la bon
        self.assertIn("casa arată parola goală „” — fie nu are parolă (încercați --password=), fie casa nu o arată",
                      output)
        self.assertIn("parolă greșită", output)
        self.lines.clear()
        code, output = self.run_check("--password=", "--bon", answer="DA")  # pe casă: 4 spații
        self.assertEqual(code, 0, output)
        self.assertIn("bon emis", output)
        self.assertIn("    DETOATE_TREMOL_PASSWORD=\n", output + "\n")

    def test_till_that_hides_the_operator_only_warns(self):
        self.device.refuse[0x6A] = "01"
        code, output = self.run_check()
        self.assertEqual(code, 0, output)
        self.assertIn("ATENȚIE   casa nu arată operatorul 1", output)

    def test_unreachable_till(self):
        self.device.unreachable = True
        code, output = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("portul casei de marcat nu se poate deschide", output)

    def test_model_info_shows_the_connection(self):
        code, output = self.run_check()
        self.assertIn("interfețe: RS232,USB,LAN — folosită acum: USB", output)
        self.assertIn("nume de articol: până la 36 caractere acceptate, 32 tipărite pe bon", output)

    def test_short_article_names_fail(self):
        self.device.model[16] = "24"
        code, output = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn("casa acceptă nume de articol de 24 caractere; aplicația trimite până la 30", output)

    def test_model_without_info_command_only_warns(self):
        self.device.model = None
        code, output = self.run_check()
        self.assertEqual(code, 0, output)
        self.assertIn("nu răspunde la comanda de model", output)

    def test_without_port_the_till_is_found_first(self):
        found = []

        def find(out):
            found.append(True)
            return "COM4", 115200

        with mock.patch.object(tremol, "serial_transport", return_value=self.device) as transport:
            code = tremol_check.main([], ask=lambda _: "nu", out=self.lines.append, find=find)
        output = "\n".join(self.lines)
        self.assertEqual((code, found), (0, [True]), output)
        transport.assert_called_once_with("COM4", 115200)
        self.assertIn("casa e pe COM4, la 115200 baud", output)
        self.assertIn("DETOATE_TREMOL_PORT=COM4", output)

    def test_till_not_found(self):
        code = tremol_check.main([], out=self.lines.append, find=lambda out: None)
        self.assertEqual(code, 1)
        self.assertIn("casa nu a fost găsită pe niciun port", "\n".join(self.lines))


class SilentPort:
    """Un port COM pe care nu răspunde nimic (alt dispozitiv, sau casa la altă viteză)."""

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def reset_input_buffer(self):
        pass

    def write(self, data):
        pass

    def read(self, n):
        return b""


class FindTillTest(unittest.TestCase):
    def test_scans_ports_and_speeds(self):
        device, tried = FakeTremol(), []

        def open_port(port, baud):
            tried.append((port, baud))
            return device if (port, baud) == ("COM4", 9600) else SilentPort()

        lines = []
        found = tremol_check.find_till(lines.append, ports=[("COM3", "Bluetooth"), ("COM4", "USB Serial Device")],
                                       open_port=open_port)
        self.assertEqual(found, ("COM4", 9600))
        self.assertEqual(tried, [("COM3", b) for b in tremol_check.SCAN_BAUDS] + [("COM4", 115200), ("COM4", 9600)])
        self.assertIn("încerc COM4 (USB Serial Device)", [line.strip() for line in lines])

    def test_port_that_cannot_open_is_skipped(self):
        device = FakeTremol()
        busy = FakeTremol()
        busy.unreachable = True
        found = tremol_check.find_till(lambda _: None, ports=[("COM1", "ocupat"), ("COM2", "casa")],
                                       open_port=lambda port, baud: busy if port == "COM1" else device)
        self.assertEqual(found, ("COM2", 115200))

    def test_no_ports(self):
        lines = []
        self.assertIsNone(tremol_check.find_till(lines.append, ports=[]))
        self.assertIn("niciun port COM", lines[0])


if __name__ == "__main__":
    unittest.main()
