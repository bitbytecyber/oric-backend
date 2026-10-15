from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import EvidenceDownloadView, FormSchemaView, SavedViewViewSet, SubmissionViewSet

router = SimpleRouter()
router.register("submissions", SubmissionViewSet, basename="submissions")
router.register("saved-views", SavedViewViewSet, basename="saved-views")

urlpatterns = [
    path("forms/schema/", FormSchemaView.as_view(), name="forms-schema"),
    path("evidence/<int:pk>/download/", EvidenceDownloadView.as_view(), name="evidence-download"),
    *router.urls,
]
