from django.urls import path

from .views import AnalyticsView, ExploreView, ExportColumnsView, ExportView, HomeView

urlpatterns = [
    path("me/home/", HomeView.as_view(), name="me-home"),
    path("explore/", ExploreView.as_view(), name="explore"),
    path("reports/analytics/", AnalyticsView.as_view(), name="reports-analytics"),
    path("reports/export/", ExportView.as_view(), name="reports-export"),
    path("reports/export-columns/", ExportColumnsView.as_view(), name="reports-export-columns"),
]
