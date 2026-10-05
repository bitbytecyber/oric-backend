from auditlog.models import LogEntry
from rest_framework import serializers, viewsets

from rbac.viewsets import RBACViewSetMixin

from .models import ActivityEvent


class ActivityEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActivityEvent
        fields = ["id", "action", "actor", "actor_label", "description", "target_id", "request_id", "path",
                  "method", "remote_addr", "metadata", "timestamp"]


class LogEntrySerializer(serializers.ModelSerializer):
    action = serializers.CharField(source="get_action_display")
    model = serializers.SerializerMethodField()
    actor_label = serializers.SerializerMethodField()

    class Meta:
        model = LogEntry
        fields = ["id", "action", "model", "object_pk", "object_repr", "changes", "actor", "actor_label", "cid",
                  "remote_addr", "timestamp"]

    def get_model(self, obj):
        return f"{obj.content_type.app_label}.{obj.content_type.model}" if obj.content_type_id else ""

    def get_actor_label(self, obj):
        return getattr(obj.actor, "email", "") if obj.actor_id else ""


class ActivityEventViewSet(RBACViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Logins, exports, downloads, workflow actions. Read-only."""

    queryset = ActivityEvent.objects.select_related("actor")
    serializer_class = ActivityEventSerializer
    capability_map = {"list": "audit.view", "retrieve": "audit.view"}
    filterset_fields = ["action", "actor"]
    search_fields = ["actor_label", "description", "path", "request_id"]


class ChangeLogViewSet(RBACViewSetMixin, viewsets.ReadOnlyModelViewSet):
    """Row-level change history from django-auditlog."""

    queryset = LogEntry.objects.select_related("content_type", "actor")
    serializer_class = LogEntrySerializer
    capability_map = {"list": "audit.view", "retrieve": "audit.view"}
    filterset_fields = ["action", "actor", "content_type__model"]
    search_fields = ["object_repr", "cid"]
