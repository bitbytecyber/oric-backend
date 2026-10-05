from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("users", views.UserViewSet, basename="users")

urlpatterns = [
    path("me/profile/", views.ProfileMeView.as_view(), name="me-profile"),
    path("me/activity/", views.MeActivityView.as_view(), name="me-activity"),
    *router.urls,
]
