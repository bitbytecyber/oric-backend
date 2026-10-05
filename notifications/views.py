from django.utils import timezone
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "kind", "title", "body", "link", "read_at", "created_at"]


class NotificationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """The signed-in user's own notifications (self-service: no capability)."""

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["kind"]

    def get_queryset(self):
        qs = Notification.objects.filter(user=self.request.user)
        if self.request.query_params.get("unread") in ("1", "true"):
            qs = qs.filter(read_at__isnull=True)
        return qs

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        n = self.get_object()
        if not n.read_at:
            n.read_at = timezone.now()
            n.save(update_fields=["read_at"])
        return Response(self.get_serializer(n).data)

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        count = self.get_queryset().filter(read_at__isnull=True).update(read_at=timezone.now())
        return Response({"updated": count})

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        return Response({"count": Notification.objects.filter(user=request.user, read_at__isnull=True).count()})
