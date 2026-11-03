from django.urls import path

from .views import AnalyticsView, BosReportView, ExploreView, ExportColumnsView, ExportView, HomeView, SummaryView

urlpatterns = [
    path("me/home/", HomeView.as_view(), name="me-home"),
    path("explore/", ExploreView.as_view(), name="explore"),
    path("reports/analytics/", AnalyticsView.as_view(), name="reports-analytics"),
    path("reports/summary/", SummaryView.as_view(), name="reports-summary"),
    path("reports/bos/", BosReportView.as_view(), name="reports-bos"),
    path("reports/export/", ExportView.as_view(), name="reports-export"),
    path("reports/export-columns/", ExportColumnsView.as_view(), name="reports-export-columns"),
]
