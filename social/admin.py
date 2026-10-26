from django.contrib import admin

from .models import Post


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ["scheduled_at", "network", "event", "status", "attempts", "published_at"]
    list_filter = ["network", "status"]
    search_fields = ["event__title", "text"]
    raw_id_fields = ["event"]
