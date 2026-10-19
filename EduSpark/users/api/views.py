from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from users.tenancy import TenantAPIMixin

from .serializers import EduTokenObtainPairSerializer, LogoutSerializer, MeSerializer


class LoginView(TokenObtainPairView):
    """POST {username, password} -> {access, refresh, email, platform_role, memberships}."""
    permission_classes = (AllowAny,)
    serializer_class = EduTokenObtainPairSerializer


class RefreshView(TokenRefreshView):
    permission_classes = (AllowAny,)


class MeView(TenantAPIMixin, APIView):
    """GET -> utilisateur courant, ses universités et l'université courante.

    En-têtes : Authorization: Bearer <access> ; X-University: <slug ou id> (optionnel).
    """
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        data = MeSerializer(request.user).data
        university = request.university
        data["current_university"] = (
            {"id": university.pk, "slug": university.slug, "name": university.name} if university else None
        )
        data["current_role"] = request.university_role
        return Response(data)


class LogoutView(APIView):
    """POST {refresh} -> blacklist du refresh token (déconnexion API)."""
    permission_classes = (IsAuthenticated,)

    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data["refresh"]).blacklist()
        except TokenError:
            return Response(
                {"detail": "Token invalide ou déjà révoqué."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_205_RESET_CONTENT)
