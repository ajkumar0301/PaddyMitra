from django.contrib import admin

from .models import Query


@admin.register(Query)
class QueryAdmin(admin.ModelAdmin):
    list_display = ("code", "timestamp", "district", "category", "farmer_feedback", "status")
    list_filter = ("status", "category", "farmer_feedback", "season", "crop_stage")
    search_fields = ("translated_query_text", "original_query_text", "district", "problem_entity")
    readonly_fields = ("timestamp",)
