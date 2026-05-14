from django.db import models


class Hook(models.Model):
    GATEWAY_PICKY = "Picky Assist"
    GATEWAY_META = "Meta WhatsApp"
    GATEWAY_OTHER = "Other"
    GATEWAY_CHOICES = [
        (GATEWAY_PICKY, "Picky Assist"),
        (GATEWAY_META, "Meta WhatsApp"),
        (GATEWAY_OTHER, "Other"),
    ]

    LANGUAGE_CHOICES = [
        ("Odia", "Odia"),
        ("Hindi", "Hindi"),
        ("Bengali", "Bengali"),
        ("Telugu", "Telugu"),
        ("Tamil", "Tamil"),
        ("English", "English"),
    ]

    STATUS_ACTIVE = "Active"
    STATUS_PAUSED = "Paused"
    STATUS_DISABLED = "Disabled"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_PAUSED, "Paused"),
        (STATUS_DISABLED, "Disabled"),
    ]

    name = models.CharField(max_length=200)
    whatsapp_number = models.CharField(max_length=30)
    gateway_provider = models.CharField(
        max_length=40, choices=GATEWAY_CHOICES, default=GATEWAY_PICKY
    )
    trigger_keyword = models.CharField(max_length=40)
    catalogue = models.ForeignKey(
        "catalogues.Catalogue", on_delete=models.PROTECT, related_name="hooks"
    )
    primary_language = models.CharField(
        max_length=20, choices=LANGUAGE_CHOICES, default="Odia"
    )
    secondary_language = models.CharField(
        max_length=20, choices=LANGUAGE_CHOICES, default="English", blank=True
    )

    stt_provider = models.CharField(max_length=50, default="OpenAI Whisper")
    tts_provider = models.CharField(max_length=50, default="OpenAI TTS")
    translation_model = models.CharField(max_length=80, default="gpt-4o-mini")
    rag_model = models.CharField(max_length=80, default="gpt-4o-mini")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    welcome_message = models.TextField(blank=True)
    webhook_url = models.CharField(max_length=500, blank=True)

    messages_processed_count = models.IntegerField(default=0)
    avg_response_time = models.FloatField(default=0.0)
    success_rate = models.FloatField(default=0.0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        unique_together = (("gateway_provider", "trigger_keyword"),)

    def save(self, *args, **kwargs):
        self.trigger_keyword = (self.trigger_keyword or "").upper().strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.trigger_keyword})"

    @property
    def api_endpoint(self):
        return f"/v1/hooks/{self.trigger_keyword.lower()}"
