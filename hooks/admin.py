from django.contrib import admin

from .models import Hook


@admin.register(Hook)
class HookAdmin(admin.ModelAdmin):
    list_display = ("name", "trigger_keyword", "gateway_provider", "catalogue", "status")
    list_filter = ("gateway_provider", "status", "primary_language")
    search_fields = ("name", "trigger_keyword", "whatsapp_number")
