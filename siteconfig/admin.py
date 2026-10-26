from django.contrib import admin

from .models import ConfigChange


@admin.register(ConfigChange)
class ConfigChangeAdmin(admin.ModelAdmin):
    list_display = ["changed_at", "user", "fields"]
    readonly_fields = ["changed_at", "user", "fields"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
