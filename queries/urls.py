from django.urls import path

from . import views

app_name = "queries"

urlpatterns = [
    path("", views.QueryListView.as_view(), name="list"),
    path("demo/", views.QueryDemoView.as_view(), name="demo"),
    path("<int:pk>/", views.QueryDetailView.as_view(), name="detail"),
    path("<int:pk>/flag/", views.flag_query, name="flag"),
    path("<int:pk>/feedback/", views.set_feedback, name="set_feedback"),
]
