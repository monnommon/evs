from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["sequence", "event_type", "entity_type", "entity_id", "created_at", "current_hash"]
    list_filter = ["event_type", "entity_type"]
    search_fields = ["entity_id", "current_hash"]
    ordering = ["sequence"]
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False