import unittest

from errors import ApiError
from search import like_escape, search_key
from tests.helpers import ApiTestCase
from validation import MISSING, cui


class SearchKeyTest(unittest.TestCase):
    def test_strips_romanian_diacritics_and_case(self):
        self.assertEqual(search_key("ROȘII Țelină Brânză Ăla Îți"), "rosii telina branza ala iti")

    def test_cedilla_variants_match_comma_variants(self):
        self.assertEqual(search_key("Şunculiţă"), search_key("Șunculiță"))

    def test_collapses_whitespace(self):
        self.assertEqual(search_key("  roșii   cherry "), "rosii cherry")

    def test_like_escape(self):
        self.assertEqual(like_escape("50%_a\\b"), "50\\%\\_a\\\\b")


class CuiTest(unittest.TestCase):
    def test_valid_codes_are_normalized(self):
        cases = [
            ("14080700", "14080700"),
            ("RO14080700", "RO14080700"),
            (" ro 1439 9840 ", "RO14399840"),
            ("0014080700", "0014080700"),   # zerourile din față nu schimbă cifra de control
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(cui({"c": value}, "c"), expected)

    def test_invalid_codes(self):
        for value in ("14080701", "1", "12345678901", "RO", "RO-14080700", "14O80700", "١٤٠٨٠٧٠٠"):
            with self.subTest(value=value):
                with self.assertRaises(ApiError):
                    cui({"c": value}, "c")

    def test_empty_and_missing(self):
        self.assertIsNone(cui({"c": "  "}, "c"))
        self.assertIsNone(cui({"c": None}, "c"))
        self.assertIs(cui({}, "c"), MISSING)


class AppTest(ApiTestCase):
    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"status": "ok"})

    def test_unknown_api_route_is_json_404(self):
        self.assertError(self.client.get("/api/nu-exista"), 404, "nu există")

    def test_wrong_method_is_json_405(self):
        self.assertError(self.client.delete("/api/health"), 405)

    def test_no_cors_headers(self):
        # intenționat: un site străin deschis în browser nu trebuie să poată apela casa
        r = self.client.get("/api/health", headers={"Origin": "http://evil.example"})
        self.assertNotIn("Access-Control-Allow-Origin", r.headers)

    def test_out_of_range_ids_are_404_not_500(self):
        for url in ("/api/products/0", "/api/orders/99999999999999999999",
                    "/api/products/99999999999999999999"):
            with self.subTest(url=url):
                self.assertError(self.client.get(url), 404)

    def test_trailing_slash_does_not_redirect(self):
        self.assertEqual(self.client.get("/api/products").status_code, 200)
        self.assertEqual(self.client.get("/api/products/").status_code, 200)


if __name__ == "__main__":
    unittest.main()
