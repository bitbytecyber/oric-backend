from django.urls import path

from .views import ExportView, HomeView, ScorecardSummaryView

urlpatterns = [
    path("me/home/", HomeView.as_view(), name="me-home"),
    path("reports/summary/", ScorecardSummaryView.as_view(), name="reports-summary"),
    path("reports/export/", ExportView.as_view(), name="reports-export"),
]
