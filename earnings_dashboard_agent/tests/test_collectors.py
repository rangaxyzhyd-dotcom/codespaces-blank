import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
import yfinance

from collectors.common import DataSourceError
from collectors.market_data import fetch_history, load_watchlist, yahoo_symbol


class CollectorTests(unittest.TestCase):
    def test_load_watchlist_normalizes_and_sorts_priority_a_first(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watchlist.csv"
            path.write_text(
                "symbol,company,exchange,priority\n xyz ,Test Corp,NSE,B\n aapl ,Apple,NSE,A\n,,NSE,B\n",
                encoding="utf-8",
            )

            rows = load_watchlist(path)
            self.assertEqual([row["symbol"] for row in rows], ["AAPL", "XYZ"])

    def test_rejects_watchlists_missing_required_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watchlist.csv"
            path.write_text("symbol,company\nAAPL,Apple\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "missing required columns"):
                load_watchlist(path)

    def test_maps_indian_symbols_for_yahoo(self):
        self.assertEqual(yahoo_symbol("SBIN", "NSE"), "SBIN.NS")
        self.assertEqual(yahoo_symbol("ABC", "BSE"), "ABC.BO")

    @patch("collectors.market_data.rate_limit")
    @patch.object(yfinance, "Ticker")
    def test_market_provider_failure_is_reported_as_data_source_error(self, ticker, _rate_limit):
        ticker.return_value.history.side_effect = requests.ConnectionError("offline")
        with self.assertRaisesRegex(DataSourceError, "Yahoo Finance request failed"):
            fetch_history("SBIN", "NSE")

    @patch("collectors.announcements._rss_headlines", side_effect=requests.ConnectionError("offline"))
    @patch("collectors.announcements._nse_announcements", return_value=[])
    def test_announcement_provider_failure_is_explicit(self, _nse, _rss):
        from collectors.announcements import fetch_announcements

        with self.assertRaisesRegex(DataSourceError, "Announcement sources failed"):
            fetch_announcements("SBIN", "NSE")

    @patch("collectors.announcements.rate_limit")
    @patch("collectors.announcements._rss_headlines", return_value=[{"id": "rss-1", "title": "Results released"}])
    @patch("collectors.announcements._nse_announcements", side_effect=requests.ConnectionError("exchange offline"))
    def test_rss_data_survives_exchange_endpoint_failure(self, _nse, _rss, _rate_limit):
        from collectors.announcements import fetch_announcements

        self.assertEqual(fetch_announcements("SBIN", "NSE")[0]["id"], "rss-1")

    def test_raw_source_failures_are_audited(self):
        from collectors.storage import fetch_cached, initialize_storage

        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"DATA_DB_PATH": str(Path(directory) / "audit.db")}):
            initialize_storage()
            with self.assertRaisesRegex(RuntimeError, "provider down"):
                fetch_cached("test", "SBIN", "test provider", 60, lambda: (_ for _ in ()).throw(RuntimeError("provider down")))
            import sqlite3

            with sqlite3.connect(Path(directory) / "audit.db") as connection:
                row = connection.execute("SELECT source, payload FROM raw_pulls").fetchone()
            self.assertEqual(row[0], "test provider")
            self.assertIn("provider down", row[1])


if __name__ == "__main__":
    unittest.main()