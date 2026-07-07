import unittest
from unittest.mock import Mock, patch

from data_sources import gold_price


class GoldPriceTests(unittest.TestCase):
    def test_fetch_current_price_uses_yahoo_fallback(self):
        fake_response = Mock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "regularMarketPrice": 4153.7,
                            "chartPreviousClose": 4167.5,
                        },
                        "indicators": {
                            "quote": [{"open": [4176.4], "low": [4127.7], "high": [4179.5], "close": [4153.7]}]
                        },
                    }
                ]
            }
        }

        with patch("data_sources.gold_price.requests.get", return_value=fake_response):
            price_point = gold_price.fetch_current_price("")

        self.assertEqual(price_point["price"], 4153.7)
        self.assertEqual(price_point["source"], "yahoo")


if __name__ == "__main__":
    unittest.main()
