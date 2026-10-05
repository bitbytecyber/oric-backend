from rest_framework.routers import SimpleRouter

from .views import ActivityEventViewSet, ChangeLogViewSet

router = SimpleRouter()
router.register("audit/activity", ActivityEventViewSet, basename="audit-activity")
router.register("audit/changes", ChangeLogViewSet, basename="audit-changes")
urlpatterns = router.urls
