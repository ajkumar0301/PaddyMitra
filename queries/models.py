from django.conf import settings
from django.db import models


class Query(models.Model):
    CATEGORY_CHOICES = [
        ("Rice Variety", "Rice Variety"),
        ("Disease", "Disease"),
        ("Fertiliser", "Fertiliser"),
        ("Water Mgmt", "Water Mgmt"),
        ("Others", "Others"),
    ]
    TASK_TYPE_CHOICES = [
        ("Diagnosis", "Diagnosis"),
        ("Variety Suitability", "Variety Suitability"),
        ("Fertiliser Rec.", "Fertiliser Recommendation"),
        ("Management Advice", "Management Advice"),
        ("Other", "Other"),
    ]
    SEASON_CHOICES = [
        ("Kharif", "Kharif"),
        ("Rabi", "Rabi"),
        ("Zaid", "Zaid"),
    ]
    CROP_STAGE_CHOICES = [
        ("Nursery", "Nursery"),
        ("Tillering", "Tillering"),
        ("Flowering", "Flowering"),
        ("Mature Grain", "Mature Grain"),
    ]
    FEEDBACK_CHOICES = [
        ("Good", "Good"),
        ("Average", "Average"),
        ("Bad", "Bad"),
    ]
    STATUS_CHOICES = [
        ("Received", "Received"),
        ("Processing", "Processing"),
        ("Responded", "Responded"),
        ("Failed", "Failed"),
        ("Escalated", "Escalated"),
        ("Flagged", "Flagged"),
    ]

    timestamp = models.DateTimeField(auto_now_add=True)
    whatsapp_number = models.CharField(max_length=30, blank=True)
    district = models.CharField(max_length=80, blank=True)

    hook = models.ForeignKey(
        "hooks.Hook", null=True, blank=True, on_delete=models.SET_NULL, related_name="queries"
    )
    trigger_keyword = models.CharField(max_length=40, blank=True)
    catalogue = models.ForeignKey(
        "catalogues.Catalogue", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="queries",
    )

    category = models.CharField(max_length=40, choices=CATEGORY_CHOICES, blank=True)
    task_type = models.CharField(max_length=40, choices=TASK_TYPE_CHOICES, blank=True)
    problem_entity = models.CharField(max_length=200, blank=True)
    season = models.CharField(max_length=20, choices=SEASON_CHOICES, blank=True)
    crop_stage = models.CharField(max_length=30, choices=CROP_STAGE_CHOICES, blank=True)
    missing_context = models.CharField(max_length=500, blank=True)

    original_query_text = models.TextField(blank=True)
    original_query_language = models.CharField(max_length=30, blank=True, default="Odia")
    original_query_voice_file = models.FileField(upload_to="audio/in/", blank=True, null=True)

    translated_query_text = models.TextField(blank=True)
    ai_response_text = models.TextField(blank=True)
    ai_response_text_local = models.TextField(blank=True)
    ai_response_voice_file = models.FileField(upload_to="audio/out/", blank=True, null=True)

    response_time_seconds = models.FloatField(default=0.0)
    farmer_feedback = models.CharField(max_length=10, choices=FEEDBACK_CHOICES, blank=True)
    source_documents = models.ManyToManyField(
        "documents.Document", blank=True, related_name="used_in_queries"
    )
    pipeline_trace = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Received")
    flagged_for_review = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="reviewed_queries",
    )
    review_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name_plural = "Queries"

    def __str__(self):
        return f"Q-{self.pk} [{self.district}] {self.translated_query_text[:40]}"

    @property
    def code(self):
        return f"Q-{self.pk:04d}"
