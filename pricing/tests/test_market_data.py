from unittest.mock import patch

from django.test import SimpleTestCase

from pricing.services.market_data import MarketDataError, option_chain, yahoo_symbol


class YahooMarketDataTests(SimpleTestCase):
    def test_b3_identifiers_map_to_yahoo(self):
        self.assertEqual(yahoo_symbol("PETR4"), "PETR4.SA")
        self.assertEqual(yahoo_symbol("petr4.sa"), "PETR4.SA")
        self.assertEqual(yahoo_symbol("PETR4 BZ Equity"), "PETR4.SA")

    def test_invalid_identifier_is_rejected(self):
        with self.assertRaises(MarketDataError):
            yahoo_symbol("PETR4 US Equity")

    @patch("pricing.services.market_data.YahooFinanceClient.chart")
    def test_snapshot_uses_only_latest_price(self, chart):
        chart.return_value = {"meta": {
            "currency": "BRL",
            "regularMarketPrice": 42.84,
            "longName": "Petróleo Brasileiro S.A. - Petrobras",
        }}

        result = option_chain("PETR4 BZ Equity")

        self.assertEqual(result["underlying_px_last"], 42.84)
        self.assertEqual(result["yahoo_symbol"], "PETR4.SA")
        self.assertEqual(result["data"], [])
        self.assertIsNone(result["dividend_yield"])
        self.assertEqual(result["source"]["provider"], "Yahoo Finance")
