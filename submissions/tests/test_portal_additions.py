import datetime
import os
import tempfile

from django.test import TestCase
from openpyxl import Workbook
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from imports.models import ImportBatch, ImportRow
from imports.services.normalize import AuthorMatcher, split_authors
from imports.services.publications import import_publications, norm_doi, pub_date
from oric_backend.testing import make_user, seed_world
from people.models import Person
from reports import bos
from scorecard.engine import irb_records
from submissions.grants import normalize_grant_data
from submissions.irb import merge_irb_reviews
from submissions.models import Contributor, Submission
from submissions.validation import validate_data


def make_sub(person, category, cycle, *, data=None, amount=None, status="verified"):
    dept = person.department
    s = Submission(category=category, cycle=cycle, owner=person, department=dept, faculty=dept.faculty,
                   status=status, data=data or {})
    s.promote()
    s.amount_pkr = amount
    s.save()
    s.sync_departments()
    return s


class ShowIfTests(TestCase):
    """IRB fields on proposals are only asked (and only required) when "Reviewed by IRB" is Yes."""

    def test_hidden_fields_are_dropped_and_not_required(self):
        base = {"irb_reviewed": "No", "irb_decision": "Approved"}
        cleaned = validate_data("grant_hec_submitted", base, draft=True)
        self.assertEqual(cleaned.get("irb_reviewed"), "No")
        self.assertNotIn("irb_decision", cleaned)

    def test_shown_fields_are_kept(self):
        cleaned = validate_data("grant_hec_submitted", {"irb_reviewed": "Yes", "irb_review_date": "2025-03-01"},
                                draft=True)
        self.assertEqual(cleaned["irb_review_date"], "2025-03-01")


class GrantNormalizeTests(TestCase):
    def test_free_text_maps_to_dropdowns(self):
        d = normalize_grant_data("grant_nonhec_approved", {
            "research_grant_name": "National Research Program for Universities", "funding_agency": ""})
        self.assertEqual(d["research_grant_name"], "NRPU")
        self.assertEqual(d["funding_agency"], "HEC")
        d = normalize_grant_data("grant_nonhec_approved", {
            "research_grant_name": "Some local fund", "funding_agency": "NED Alumni Association (NEDAASC)"})
        self.assertEqual(d["funding_agency"], "NEDAASC")


class PublicationParsingTests(TestCase):
    def test_pub_date_precision(self):
        self.assertEqual(pub_date(2024.0), ("2024-01-01", "year"))  # year only -> FY ending that year
        self.assertEqual(pub_date("2024"), ("2024-01-01", "year"))
        self.assertEqual(pub_date(datetime.date(2025, 12, 4)), ("2025-12-04", "day"))
        self.assertEqual(pub_date("4 December 2025,"), ("2025-12-04", "day"))
        self.assertEqual(pub_date("May 2024")[1], "month")
        self.assertEqual(pub_date(None), (None, ""))

    def test_doi_and_author_split(self):
        self.assertEqual(norm_doi("https://doi.org/10.1016/J.X.2024.1 "), "10.1016/j.x.2024.1")
        self.assertEqual(split_authors("Khan, A. R., Uddin, R. and M. A. Hasan"),
                         ["Khan, A. R", "Uddin, R", "M. A. Hasan"])


class AuthorMatcherTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        w = seed_world()
        cls.riaz = Person.objects.create(full_name="Riaz Uddin", department=w.eed)
        cls.ahmed = Person.objects.create(full_name="Ahmed Raza Khan", department=w.ced)
        cls.ali = Person.objects.create(full_name="Ali Khan", department=w.eed)

    def test_full_name_initials_and_ambiguous(self):
        m = AuthorMatcher()
        self.assertEqual(m.match("Dr. Riaz Uddin")[0], self.riaz)
        person, _, how = m.match("Khan, A. R.")
        self.assertEqual((person, how), (self.ahmed, "initials"))
        person, sugg, how = m.match("Khan, A.")  # fits both Ahmed Raza Khan and Ali Khan
        self.assertIsNone(person)
        self.assertEqual(how, "ambiguous")
        self.assertEqual({s["person_id"] for s in sugg}, {self.ahmed.pk, self.ali.pk})
        self.assertEqual(m.match("Zhang, W.")[2], "none")


class PublicationImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.w = seed_world()
        cls.riaz = Person.objects.create(full_name="Riaz Uddin", department=cls.w.eed)

    def _xlsx(self, rows):
        wb = Workbook()
        ws = wb.active
        ws.append(["S. No", "SJR", "Clarivate", "Authors", "Title", "Journal", "DOI", "Year of Publication"])
        for r in rows:
            ws.append(r)
        fd, path = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        wb.save(path)
        self.addCleanup(os.remove, path)
        return path

    def test_import_matches_dedupes_and_queues(self):
        day = self.w.cycle.starts_on + datetime.timedelta(days=20)
        path = self._xlsx([
            [1, "Q1", "Q2 in EE", "Riaz Uddin, J. Smith", "Paper One", "J. Power", "https://doi.org/10.1016/ABC", day],
            [2, "Q1", "", "R. Uddin", "Paper One again", "J. Power", "10.1016/abc", day],  # same DOI
            [3, "Q2", "", "J. Smith, K. Lee", "Paper Two", "J. Other", "10.1016/def", day],  # no NED author
        ])
        batch = ImportBatch.objects.create(kind=ImportBatch.Kind.PUBLICATIONS)
        stats = import_publications(batch, path)
        self.assertEqual(stats["created"], 2)
        self.assertEqual(stats["duplicates"], 1)
        paper = Submission.objects.get(category="journal_article", title="Paper One")
        self.assertEqual(paper.owner, self.riaz)
        self.assertEqual(paper.cycle, self.w.cycle)
        self.assertEqual(paper.data["sjr_quartile"], "Q1")
        self.assertEqual(ImportRow.objects.filter(batch=batch, status=ImportRow.Status.UNMATCHED).count(), 1)
        # a second run creates nothing
        again = import_publications(ImportBatch.objects.create(kind=ImportBatch.Kind.PUBLICATIONS), path)
        self.assertEqual(again["created"], 0)


class IrbAndBosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.w = w = seed_world()
        cls.pi = Person.objects.create(full_name="Sana Javed", department=w.eed)
        cls.prop = make_sub(cls.pi, "grant_hec_submitted", w.cycle, data={"research_proposal_title": "Smart Grid Study"})
        cls.legacy = make_sub(cls.pi, "irb_review", w.cycle,
                              data={"research_proposal_title": "Smart grid study", "irb_decision": "Approved"})
        cls.orphan = make_sub(cls.pi, "irb_review", w.cycle, data={"research_proposal_title": "Unrelated proposal title"})

    def test_merge_flags_proposal_and_bx_count_is_unchanged(self):
        base = Submission.objects.filter(status="verified", cycle=self.w.cycle)
        before = sum(qs.count() for qs in irb_records(base))
        merge_irb_reviews(cycle=self.w.cycle, apply=True)
        self.prop.refresh_from_db()
        self.legacy.refresh_from_db()
        self.assertEqual(self.prop.data["irb_reviewed"], "Yes")
        self.assertEqual(self.legacy.data["_merged_into"], self.prop.pk)
        legacy, flagged = irb_records(base)
        self.assertEqual(list(legacy), [self.orphan])
        self.assertEqual(list(flagged), [self.prop])
        self.assertEqual(legacy.count() + flagged.count(), before)

    def test_bos_counts_department_records(self):
        make_sub(self.pi, "grant_hec_approved", self.w.cycle, amount=2_000_000, data={"research_proposal_title": "Approved one"})
        make_sub(self.pi, "journal_article", self.w.cycle, data={"title": "Paper W", "hjrs_category": "W"})
        make_sub(self.pi, "journal_article", self.w.cycle, data={"title": "Pending X", "hjrs_category": "X"},
                 status="submitted")
        rows = {r["no"]: r for r in bos.compute(Submission.objects.all(), self.w.eed, self.w.cycle)["rows"]}
        self.assertEqual(rows["1(a)(i)"]["value"], 1)
        self.assertEqual(rows["1(a)(ii)"]["value"], 1)
        self.assertEqual(rows["2(a)"]["value"], 2_000_000)
        self.assertEqual(rows["14"]["value"], 1)
        self.assertEqual(rows["15"]["value"], 0)  # pending only counts with include_pending
        self.assertFalse(rows["9(c)"]["tracked"])
        rows = {r["no"]: r for r in bos.compute(Submission.objects.all(), self.w.eed, self.w.cycle,
                                                include_pending=True)["rows"]}
        self.assertEqual(rows["15"]["value"], 1)
        other = {r["no"]: r for r in bos.compute(Submission.objects.all(), self.w.ced, self.w.cycle)["rows"]}
        self.assertEqual(other["1(a)(i)"]["value"], 0)
        self.assertTrue(bos.workbook(bos.compute(Submission.objects.all(), self.w.eed, self.w.cycle)))


class ClaimTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.w = w = seed_world()
        cls.user = make_user("claimer@x.test", role="faculty", department=w.eed)  # "Dr. Claimer"
        owner = Person.objects.create(full_name="Riaz Uddin", department=w.eed)
        cls.paper = make_sub(owner, "journal_article", w.cycle,
                             data={"title": "Shared paper", "authors_text": "Uddin, R., Claimer, D."})
        cls.other = make_sub(owner, "journal_article", w.cycle,
                             data={"title": "Not theirs", "authors_text": "Uddin, R."})

    def test_claimable_and_claim(self):
        self.client.force_authenticate(self.user)
        r = self.client.get("/api/v1/submissions/claimable/")
        self.assertEqual(r.status_code, 200)
        ids = [x["id"] for x in r.json()["data"]]
        self.assertEqual(ids, [self.paper.pk])
        r = self.client.post(f"/api/v1/submissions/{self.paper.pk}/claim/")
        self.assertEqual(r.status_code, 200, r.content)
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.status, "submitted")  # back to ORIC to verify the authorship
        self.assertTrue(Contributor.objects.filter(submission=self.paper, person=self.user.person).exists())
        r = self.client.post(f"/api/v1/submissions/{self.other.pk}/claim/")
        self.assertEqual(r.status_code, 400)

    def test_retired_category_cannot_be_added(self):
        from submissions.access import can_add
        self.assertFalse(can_add(self.user, category="irb_review"))
        self.assertTrue(can_add(self.user, category="journal_article", person=self.user.person))
