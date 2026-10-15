from rest_framework.routers import SimpleRouter

from .views import ImportBatchViewSet, ImportRowViewSet

router = SimpleRouter()
router.register("imports", ImportBatchViewSet, basename="imports")
router.register("import-rows", ImportRowViewSet, basename="import-rows")

urlpatterns = router.urls
