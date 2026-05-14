from django.urls import path

from . import views

app_name = "hooks"

urlpatterns = [
    path("", views.HookListView.as_view(), name="list"),
    path("new/", views.HookCreateView.as_view(), name="create"),
    path("<int:pk>/", views.HookDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.HookUpdateView.as_view(), name="edit"),
    path("<int:pk>/delete/", views.HookDeleteView.as_view(), name="delete"),
    path("<int:pk>/toggle/", views.toggle_hook, name="toggle"),
    path("webhook/pickyassist/", views.PickyAssistWebhookView.as_view(), name="webhook_pickyassist"),
]
