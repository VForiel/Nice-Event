from django.contrib import admin

from .models import Source


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "is_active", "last_run_at", "last_ok", "last_found", "last_created"]
    list_filter = ["kind", "is_active", "last_ok"]
    prepopulated_fields = {"slug": ["name"]}
    readonly_fields = ["last_run_at", "last_ok", "last_message", "last_found", "last_created", "last_updated", "last_empty_runs"]
