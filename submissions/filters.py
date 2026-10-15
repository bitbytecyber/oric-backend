"""Every filter the Submissions table, Explore, exports and the scorecard drill-down share."""
import django_filters as df
from django.db.models import F, Q

from .models import Contributor, Submission

SubmissionDepartment = Submission.departments.through


class CSVInFilter(df.BaseInFilter, df.CharFilter):
    pass


class NumberInFilter(df.BaseInFilter, df.NumberFilter):
    pass


class SubmissionFilter(df.FilterSet):
    cycle = NumberInFilter(field_name="cycle_id")
    year = NumberInFilter(field_name="cycle__year")
    year_from = df.NumberFilter(field_name="cycle__year", lookup_expr="gte")
    year_to = df.NumberFilter(field_name="cycle__year", lookup_expr="lte")
    faculty = NumberInFilter(method="filter_faculty")
    department = NumberInFilter(method="filter_department")
    person = df.NumberFilter(method="filter_person")
    owner = df.NumberFilter(field_name="owner_id")
    pillar = CSVInFilter(field_name="pillar")
    category = CSVInFilter(field_name="category")
    status = CSVInFilter(field_name="status")
    scope_level = CSVInFilter(field_name="scope_level")
    funding_source = CSVInFilter(field_name="funding_source")
    organization = NumberInFilter(field_name="organization_id")
    source = CSVInFilter(field_name="source")
    amount_min = df.NumberFilter(field_name="amount_pkr", lookup_expr="gte")
    amount_max = df.NumberFilter(field_name="amount_pkr", lookup_expr="lte")
    date_from = df.DateFilter(field_name="event_date", lookup_expr="gte")
    date_to = df.DateFilter(field_name="event_date", lookup_expr="lte")
    has_evidence = df.BooleanFilter(method="filter_has_evidence")
    needs_match = df.BooleanFilter(field_name="needs_match")
    on_behalf = df.BooleanFilter(method="filter_on_behalf")
    filed_or_granted = CSVInFilter(field_name="data__filed_or_granted")
    policy_type = CSVInFilter(field_name="data__policy_type")
    q = df.CharFilter(method="filter_q")

    class Meta:
        model = Submission
        fields = []

    def filter_faculty(self, qs, name, value):
        if not value:
            return qs
        links = SubmissionDepartment.objects.filter(department__faculty_id__in=value).values("submission_id")
        return qs.filter(Q(faculty_id__in=value) | Q(pk__in=links))

    def filter_department(self, qs, name, value):
        if not value:
            return qs
        links = SubmissionDepartment.objects.filter(department_id__in=value).values("submission_id")
        return qs.filter(Q(department_id__in=value) | Q(pk__in=links))

    def filter_person(self, qs, name, value):
        contributed = Contributor.objects.filter(person_id=value).values("submission_id")
        return qs.filter(Q(owner_id=value) | Q(pk__in=contributed))

    def filter_has_evidence(self, qs, name, value):
        q = Q(files__isnull=False) | ~Q(evidence_links=[])
        return qs.filter(q).distinct() if value else qs.exclude(q)

    def filter_on_behalf(self, qs, name, value):
        q = Q(submitted_by__isnull=False, owner__user__isnull=False) & ~Q(owner__user_id=F("submitted_by_id"))
        return qs.filter(q) if value else qs.exclude(q)

    def filter_q(self, qs, name, value):
        value = (value or "").strip()
        if not value:
            return qs
        contributed = Contributor.objects.filter(
            Q(name__icontains=value) | Q(person__full_name__icontains=value)).values("submission_id")
        return qs.filter(Q(title__icontains=value) | Q(owner__full_name__icontains=value)
                         | Q(organization__name__icontains=value) | Q(pk__in=contributed)
                         | Q(import_ref__iexact=value))

