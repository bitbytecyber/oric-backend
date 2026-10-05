from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("departments", views.DepartmentViewSet, basename="departments")
router.register("reporting-cycles", views.ReportingCycleViewSet, basename="reporting-cycles")
router.register("team-members", views.TeamMemberViewSet, basename="team-members")
router.register("contact-messages", views.ContactMessageViewSet, basename="contact-messages")

urlpatterns = [
    path("public/site/", views.PublicSiteView.as_view(), name="public-site"),
    path("public/contact/", views.ContactCreateView.as_view(), name="contact-create"),
    *router.urls,
]
