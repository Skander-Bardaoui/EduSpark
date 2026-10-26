from django.urls import path

from .views import LoginView, LogoutView, MeView, RefreshView

urlpatterns = [
    path("token/", LoginView.as_view(), name="token_obtain"),
    path("token/refresh/", RefreshView.as_view(), name="token_refresh"),
    path("logout/", LogoutView.as_view(), name="token_logout"),
    path("me/", MeView.as_view(), name="me"),
]
