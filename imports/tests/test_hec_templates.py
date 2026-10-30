"""HEC workbook templates across years (FY 2019-20 Annexures, FY 2020-21 Index, FY 2021-22 onward).

The workbook-backed tests need the yearly files in ``.local/hec/hec_<FY>.xlsx`` and are skipped without them."""
import os
import unittest

from django.test import TestCase

from imports.services.hec_workbook import _clean_date, _column_map, _title_key, canon_sheet
from imports.services.normalize import to_date

HEC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", ".local", "hec")


def _wb(fy):
    return os.path.join(HEC_DIR, f"hec_{fy}.xlsx")


class _Sheet:
    def __init__(self, rows):
        self.rows = rows

    def cell(self, r, c):
        class _C:
            value = self.rows[r - 1][c - 1] if r <= len(self.rows) and c <= len(self.rows[r - 1]) else None
        return _C


class TemplateHelpersTests(TestCase):
    def test_rupee_columns(self):
        from imports.services.hec_workbook import TableHit, _rupee_columns

        field = {"contract_value": {"type": "decimal", "label": "Contract value (PKR million)"}}
        hit = TableHit("B.xviii", "Index-B", 1, 1, 5, {"A": "Contract Value (PKR Millions)"})
        rupees = _Sheet([["h"], [11000], [8000], [25000], [9000]])  # an Rs 8,000 test among rupee amounts
        millions = _Sheet([["h"], [2.5], [0.8], [1900], [12]])
        self.assertEqual(_rupee_columns(rupees, hit, {"A": "contract_value"}, field, ["A"]), {"A"})
        self.assertEqual(_rupee_columns(millions, hit, {"A": "contract_value"}, field, ["A"]), set())

    def test_sheet_names_are_canonical(self):
        self.assertEqual(canon_sheet("Index D"), "Index-D")
        self.assertEqual(canon_sheet(" index-b "), "Index-B")
        self.assertEqual(canon_sheet("Uploade PC"), "Uploade PC")

    def test_tables_classified_by_title(self):
        # FY 2020-21 numbers its tables differently; the title decides the key
        self.assertEqual(_title_key("D", "Exhibitions / Showcasing Events ... Arranged by ORIC"), "D.v")
        self.assertEqual(_title_key("B", "Contract Research Awarded by Industry or Government Organizations "
                                         "(National / International)"), "B.xiii")

    def test_year_wins_over_fuzzy_parse(self):
        self.assertEqual(to_date("July 2020(delayed due to COVID)"), "2020-07-01")
        self.assertEqual(to_date("9th and 10th July 2019"), "2019-07-10")
        self.assertEqual(to_date("30–31 July 2024"), "2024-07-31")
        self.assertEqual(to_date("Ref 1234 dated 5 May 2021"), "2021-05-05")
        self.assertEqual(to_date("5th sept, 2024"), "2024-09-05")
        self.assertEqual(to_date("Room 2010, 5 May 2021"), "2021-05-05")  # the year after the month
        self.assertEqual(to_date("02-27-2024-02-27-2026"), "2024-02-27")  # a range starts at its first year

    def test_date_sanitiser(self):
        import datetime

        flags = []  # 2021 typed into a date-formatted cell reads back as 1905-07-13
        typed_year = datetime.datetime(1899, 12, 30) + datetime.timedelta(days=2021)
        self.assertEqual(_clean_date(typed_year, "event_date", flags), "2021-01-01")
        self.assertIn("only the year 2021", flags[0])
        flags = []
        self.assertIsNone(_clean_date("3916-03-28", "contract_signed_date", flags))
        self.assertIn("impossible date", flags[0])

    def test_fallback_column_only_when_target_free(self):
        spec = [(r"date of proposal approval", "proposal_approval_date"), (r"date of approval", "?proposal_approval_date")]
        both = _column_map(spec, {"A": "Date of Proposal Approval", "B": "Date of Approval"})
        self.assertEqual(both, {"A": "proposal_approval_date", "B": None})
        only_old = _column_map(spec, {"B": "Date of Approval"})
        self.assertEqual(only_old, {"B": "proposal_approval_date"})


@unittest.skipUnless(os.path.isdir(HEC_DIR), "yearly HEC workbooks not present (.local/hec/)")
class WorkbookTemplateTests(TestCase):
    def test_template_detection(self):
        from imports.services.hec_workbook import Book, detect_template

        expected = {"2019-20": "annexure_2019", "2020-21": "index_2020", "2021-22": "index_2021",
                    "2024-25": "index_2021", "2025-26": "index_2021"}
        for fy, template in expected.items():
            if os.path.exists(_wb(fy)):
                with self.subTest(fy=fy):
                    self.assertEqual(detect_template(Book(_wb(fy))), template)

    def test_2020_21_tables(self):
        if not os.path.exists(_wb("2020-21")):
            self.skipTest("FY 2020-21 workbook missing")
        from imports.services.hec_workbook import Book, locate_tables

        keys = {h.key for h in locate_tables(Book(_wb("2020-21")), "index_2020")}
        self.assertTrue({"B.iii", "B.vi", "B.xiii", "C.v", "D.iii", "D.v"} <= keys)
        self.assertNotIn("B.i", keys)  # no grant-opportunity table that year
        self.assertNotIn("C.i", keys)  # nor policies

    def test_table_only_import(self):
        if not os.path.exists(_wb("2020-21")):
            self.skipTest("FY 2020-21 workbook missing")
        import datetime

        from imports.models import ImportBatch, ImportRow
        from imports.services.hec_workbook import import_workbook
        from org.models import ReportingCycle

        cycle = ReportingCycle.objects.create(year=2021, label="FY 2020-21", starts_on=datetime.date(2020, 7, 1),
                                              ends_on=datetime.date(2021, 6, 30))
        for _ in range(2):  # importing the same table twice replaces it
            batch = ImportBatch.objects.create(kind="hec_workbook", original_name="t", cycle=cycle)
            stats = import_workbook(batch, _wb("2020-21"), only=["B.iii"])
        self.assertEqual(stats["template"], "index_2020")
        rows = ImportRow.objects.filter(batch__cycle=cycle)
        self.assertEqual(set(rows.values_list("table", flat=True)), {"B.iii"})
        self.assertEqual(rows.count(), stats["created"])
        from submissions.models import Submission

        self.assertEqual(Submission.objects.filter(cycle=cycle).count(), stats["created"])  # replaced, not doubled
        bad = ImportBatch.objects.create(kind="hec_workbook", original_name="t", cycle=cycle)
        with self.assertRaises(ValueError):  # a table this template lacks must not wipe anything
            import_workbook(bad, _wb("2020-21"), only=["B.i"])
        self.assertEqual(Submission.objects.filter(cycle=cycle).count(), stats["created"])
        cycle.refresh_from_db()
        self.assertEqual(cycle.framework, "hec_2020")
        # "Date of Approval" is that year's only approval-date column
        self.assertTrue(rows.filter(parsed__has_key="proposal_approval_date").exists())


class RepairImportDatesTests(TestCase):
    def test_redates_mis_yeared_event(self):
        from django.core.management import call_command

        from imports.models import ImportBatch, ImportRow
        from oric_backend.testing import seed_world
        from submissions.models import Submission

        w = seed_world()
        batch = ImportBatch.objects.create(kind="hec_workbook", cycle=w.cycle, status="applied")
        s = Submission(category="exhibition", cycle=w.cycle, status="verified", source=Submission.Source.EXCEL,
                       data={"title": "Expo", "event_date": "2030-07-31"})
        s.promote()
        s.save()
        row = ImportRow.objects.create(batch=batch, ref="Index-D!212", table="D.v", status="created", submission=s,
                                       raw={"Date of Event": "30–31 July 2024"},
                                       parsed={"title": "Expo", "event_date": "2030-07-31"})
        call_command("repair_import_dates", "--batch", str(batch.pk), stdout=open(os.devnull, "w"))
        row.refresh_from_db()
        self.assertEqual(row.parsed["event_date"], "2030-07-31")  # report only
        call_command("repair_import_dates", "--batch", str(batch.pk), "--apply", stdout=open(os.devnull, "w"))
        row.refresh_from_db()
        s.refresh_from_db()
        self.assertEqual(row.parsed["event_date"], "2024-07-31")
        self.assertEqual(str(s.event_date), "2024-07-31")
