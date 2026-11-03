import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from io import BytesIO

os.environ["ENABLE_SCHEDULER"] = "false"
_temporary_data = tempfile.TemporaryDirectory()
os.environ["DATA_DB_PATH"] = str(Path(_temporary_data.name) / "dashboard.db")

from dashboard.app import TABLE_COLUMNS, create_app


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(create_app())
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        _temporary_data.cleanup()

    def test_dashboard_returns_54_rows_with_priority_a_first(self):
        response = self.client.get("/api/stocks")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 54)
        self.assertEqual(len(payload["columns"]), 13)
        self.assertTrue(all(stock["priority"] == "A" for stock in payload["stocks"][:8]))

    def test_priority_filter_and_stock_brief(self):
        response = self.client.get("/api/stocks?priority=A")

        self.assertEqual(response.json()["count"], 8)
        self.assertEqual(self.client.get("/stocks/SBIN").status_code, 200)
        self.assertEqual(self.client.get("/api/stocks/UNKNOWN").status_code, 404)

    def test_excel_export_has_one_row_per_watchlist_symbol_and_13_columns(self):
        response = self.client.get("/api/export.xlsx")
        workbook = load_workbook(BytesIO(response.content), read_only=True)
        sheet = workbook.active

        self.assertEqual(response.status_code, 200)
        self.assertEqual(sheet.max_row, 55)
        self.assertEqual(sheet.max_column, len(TABLE_COLUMNS))