from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("auth/", views.auth_view, name="auth"),
]
