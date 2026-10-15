from django.urls import path

from . import views

urlpatterns = [
    path("scorecard/", views.ScorecardView.as_view(), name="scorecard"),
    path("scorecard/overrides/", views.OverrideView.as_view(), name="scorecard-overrides"),
    path("scorecard/profile/", views.InstitutionProfileView.as_view(), name="scorecard-profile"),
    path("scorecard/profile/clone/", views.CloneProfileView.as_view(), name="scorecard-profile-clone"),
    path("scorecard/hec-workbook/", views.HecWorkbookView.as_view(), name="scorecard-hec-workbook"),
]
