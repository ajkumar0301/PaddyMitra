from django.urls import path

from . import views

app_name = "api_endpoints"

urlpatterns = [
    path("", views.APIListView.as_view(), name="list"),
    path("create/", views.create_api_from_query, name="create_from_query"),
    path("<uuid:public_id>/", views.APIDetailView.as_view(), name="detail"),
    path("<uuid:public_id>/delete/", views.delete_api, name="delete"),
    path("<uuid:public_id>/rotate/", views.rotate_token, name="rotate"),
]
