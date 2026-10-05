from rest_framework.routers import SimpleRouter

from .views import NotificationViewSet

router = SimpleRouter()
router.register("notifications", NotificationViewSet, basename="notifications")
urlpatterns = router.urls
