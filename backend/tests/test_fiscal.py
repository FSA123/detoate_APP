import os
import subprocess
import sys
import unittest
from unittest import mock

import fiscal
import tremol
from tests.fake_tremol import FakeTremol
from tests.helpers import ApiTestCase

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RECEIPT = fiscal.Receipt(
    order_id=7,
    lines=(fiscal.SaleLine("Roșii cherry", "B", 899, 1250, 1124),),
    total_bani=1124,
    payment_method="cash",
    cash_received_bani=2000,
    buyer_cui="RO123",
)


class FiscalModuleTest(unittest.TestCase):
    def test_simulated_receipt(self):
        with mock.patch.object(fiscal, "SIMULATE", True):
            result = fiscal.send_receipt(RECEIPT)
        self.assertEqual(
            (result.ok, result.doc_number, result.receipt_number, result.simulated),
            (True, 7, "SIM-7", True),
        )
        self.assertEqual(result.raw.splitlines(), [
            "CIF client: RO123",
            "Roșii cherry                   1,250 x 8,99 = 11,24 B",
            "TOTAL 11,24",
            "NUMERAR 20,00  REST 8,76",
        ])

    def test_card_receipt_text(self):
        card = fiscal.Receipt(RECEIPT.order_id, RECEIPT.lines, 1124, "card", None)
        with mock.patch.object(fiscal, "SIMULATE", True):
            self.assertEqual(fiscal.send_receipt(card).raw.splitlines()[-1], "CARD 11,24")

    def test_without_simulation_and_without_adapter_raises(self):
        with mock.patch.object(fiscal, "SIMULATE", False):
            with self.assertRaises(fiscal.FiscalError):
                fiscal.send_receipt(RECEIPT)

    def simulate_flag(self, value):
        """(SIMULATE, stderr) la importul modulului într-un proces nou, cu variabila dată."""
        env = {k: v for k, v in os.environ.items() if k not in ("DETOATE_FISCAL_SIMULATE", "DETOATE_TREMOL_PORT")}
        if value is not None:
            env["DETOATE_FISCAL_SIMULATE"] = value
        p = subprocess.run(
            [sys.executable, "-c", "import fiscal; print(fiscal.SIMULATE)"],
            cwd=BACKEND_DIR, env=env, capture_output=True, text=True, check=True,
        )
        return p.stdout.strip(), p.stderr

    def test_simulation_is_off_unless_requested(self):
        # bonuri false în magazin = vânzări fără bon fiscal; simularea se cere explicit
        for value in (None, "", "0", "false", "no"):
            with self.subTest(value=value):
                self.assertEqual(self.simulate_flag(value), ("False", ""))

    def test_simulation_on_warns_at_startup(self):
        flag, stderr = self.simulate_flag("1")
        self.assertEqual(flag, "True")
        self.assertIn("MOD SIMULARE FISCALĂ", stderr)


def configured(simulate=False, port=""):
    """Configurarea casei, ca din variabilele de mediu."""
    return mock.patch.multiple(fiscal, SIMULATE=simulate, TREMOL_PORT=port)


class FiscalModeTest(ApiTestCase):
    def test_modes(self):
        cases = [((False, ""), "none"), ((True, ""), "simulate"), ((False, "COM3"), "tremol"), ((True, "COM3"), "conflict")]
        for (simulate, port), mode in cases:
            with self.subTest(mode=mode), configured(simulate, port):
                body = self.client.get("/api/fiscal/status").get_json()
                self.assertEqual((fiscal.mode(), body["mode"], body["simulated"]), (mode, mode, mode == "simulate"))
                self.assertEqual(body["problem"] is None, mode in ("simulate", "tremol"))

    def test_conflicting_configuration_refuses_receipts(self):
        with configured(True, "COM3"), self.assertRaises(fiscal.FiscalError) as ctx:
            fiscal.send_receipt(RECEIPT)
        self.assertIn("păstrați doar una", str(ctx.exception))


class TremolDispatchTest(unittest.TestCase):
    def setUp(self):
        self.device = FakeTremol()
        patches = [configured(port="COM9"),
                   mock.patch.object(fiscal, "_tremol", return_value=tremol.TremolPrinter(self.device, timeout=0.3))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_receipt_goes_to_the_till(self):
        result = fiscal.send_receipt(RECEIPT)
        self.assertEqual(result, fiscal.FiscalResult(ok=True, doc_number=1201, receipt_number="42",
                                                     message="OK", raw="", simulated=False))
        self.assertEqual(self.device.printed[0]["cui"], "RO123")

    def test_refusal_is_a_failed_result(self):
        self.device.refuse[0x31] = "14"
        result = fiscal.send_receipt(RECEIPT)
        self.assertFalse(result.ok)
        self.assertIn("lipsă hârtie", result.message)

    def test_device_problems_become_fiscal_errors(self):
        cases = [
            (lambda: setattr(self.device, "unreachable", True), "Legătura cu casa de marcat"),
            (lambda: setattr(self.device, "receipt", {"lines": [{}], "total": 0, "payment": {"type": 0}}), "plata începută"),
        ]
        for arrange, message in cases:
            with self.subTest(message=message):
                self.setUp()
                arrange()
                with self.assertRaises(fiscal.FiscalError) as ctx:
                    fiscal.send_receipt(RECEIPT)
                self.assertIn(message, str(ctx.exception))

    def test_unknown_vat_class_is_a_fiscal_error(self):
        bad = fiscal.Receipt(1, (fiscal.SaleLine("X", "Q", 100, 1000, 100),), 100, "cash", 100)
        with self.assertRaises(fiscal.FiscalError):
            fiscal.send_receipt(bad)
        self.assertEqual(self.device.executed, [])

    def test_daily_report(self):
        fiscal.send_receipt(RECEIPT)
        report = fiscal.daily_report(zeroing=True)
        self.assertEqual((report.ok, report.z_number, report.total_bani, report.cash_bani, report.simulated),
                         (True, 18, 1124, 1124, False))


if __name__ == "__main__":
    unittest.main()
