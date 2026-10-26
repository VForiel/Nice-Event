from django.contrib import admin

from .models import Commune, Venue


@admin.register(Commune)
class CommuneAdmin(admin.ModelAdmin):
    list_display = ["name", "insee", "postcodes", "metropole", "coastal", "population"]
    list_filter = ["metropole", "coastal"]
    search_fields = ["name", "insee", "postcodes"]


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ["name", "address", "commune", "precise", "created_at"]
    list_filter = ["precise"]
    search_fields = ["name", "address", "commune__name"]
    autocomplete_fields = ["commune"]
    readonly_fields = ["created_by", "created_at"]
