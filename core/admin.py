from django.contrib import admin

from .models import Announcement, Ban, ContactMessage, JobRun, LoginFailure


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display = ["created_at", "name", "email", "subject", "handled"]
    list_filter = ["handled", "subject"]
    search_fields = ["name", "email", "message"]


@admin.register(Ban)
class BanAdmin(admin.ModelAdmin):
    list_display = ["ip", "until", "reason", "created_at"]
    search_fields = ["ip"]


@admin.register(LoginFailure)
class LoginFailureAdmin(admin.ModelAdmin):
    list_display = ["created_at", "ip", "username"]
    search_fields = ["ip", "username"]


@admin.register(JobRun)
class JobRunAdmin(admin.ModelAdmin):
    list_display = ["name", "last_started", "last_finished", "last_ok"]


admin.site.register(Announcement)
