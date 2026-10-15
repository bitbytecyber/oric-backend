from django.test import TestCase

from oric_backend.testing import seed_world
from scorecard.engine import band_score, compute
from scorecard.kpis import KPIS, PCT_2_5, SCORED
from submissions.models import Submission


class EngineTests(TestCase):
    def test_kpi_maxima_total_100(self):
        self.assertEqual(sum(k["max"] for k in SCORED), 100)
        self.assertEqual(len({k["code"] for k in KPIS}), len(KPIS))

    def test_band_score(self):
        self.assertEqual(band_score(PCT_2_5, 0), 0)
        self.assertEqual(band_score(PCT_2_5, 0.9), 0)
        self.assertEqual(band_score(PCT_2_5, 1), 0.5)
        self.assertEqual(band_score(PCT_2_5, 25), 1.5)
        self.assertEqual(band_score(PCT_2_5, 100), 2.5)

    def test_only_verified_count_unless_forecast(self):
        w = seed_world()
        for status in ("verified", "submitted"):
            s = Submission(category="policy_advocacy", cycle=w.cycle, status=status, data={"brief": "b"})
            s.promote()
            s.save()
        row = lambda sc: next(r for sec in sc["sections"] for r in sec["rows"] if r["code"] == "B.xi")  # noqa: E731
        self.assertEqual(row(compute(w.cycle))["reported"], 1)
        self.assertEqual(row(compute(w.cycle, include_pending=True))["reported"], 2)
        # 2 of 100 PhD faculty = 2% -> 0.5
        self.assertEqual(row(compute(w.cycle, include_pending=True))["score"], 0.5)
