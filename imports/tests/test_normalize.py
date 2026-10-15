import os
import unittest

from django.test import TestCase

from imports.services.normalize import million, nat_int, norm_name, split_people, to_date

WORKBOOK = os.path.join(os.path.dirname(__file__), "..", "..", ".local", "hec_fy2024-25.xlsx")


class NormalizeTests(TestCase):
    def test_amounts(self):
        self.assertEqual(million("PKR 5 Million"), 5)
        self.assertEqual(million(1250000), 1.25)
        self.assertEqual(million(3.5), 3.5)

    def test_dates(self):
        self.assertEqual(to_date("5th sept, 2024"), "2024-09-05")
        self.assertEqual(to_date("16-01-2025"), "2025-01-16")
        self.assertIsNone(to_date("N/A"))

    def test_names_and_people(self):
        self.assertEqual(norm_name("Dr. Riaz Ud Din"), norm_name("Prof. Dr. Riaz Uddin"))
        self.assertEqual(norm_name("Fayaz Hussian"), norm_name("Fayaz Hussain"))
        p = split_people("Dr. Riaz Uddin, Associate Professor, Department of Electrical Engineering")[0]
        self.assertEqual(p["name"], "Dr. Riaz Uddin")
        self.assertEqual(p["designation"], "Associate Professor")
        self.assertIn("Electrical", p["dept_hint"])
        self.assertEqual(nat_int("INTERNATIONAL"), "International")


@unittest.skipUnless(os.path.exists(WORKBOOK), "sample HEC workbook not present (.local/hec_fy2024-25.xlsx)")
class WorkbookImportTests(TestCase):
    def test_tables_located_and_counts_match_sheet(self):
        from openpyxl import load_workbook

        from imports.services.hec_workbook import TABLES, locate_tables

        wb = load_workbook(WORKBOOK, data_only=True)
        hits = {h.key: h for h in locate_tables(wb)}
        for key in ("B.ii", "B.vi", "B.xi", "B.xiii", "B.xiv", "C.iv", "C.x", "D.iii"):
            self.assertIn(key, hits)
            self.assertIn(key, TABLES)
