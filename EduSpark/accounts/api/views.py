from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import EduTokenObtainPairSerializer, LogoutSerializer, MeSerializer


class LoginView(TokenObtainPairView):
    """POST {username, password} -> {access, refresh, role, email}."""
    permission_classes = (AllowAny,)
    serializer_class = EduTokenObtainPairSerializer


class RefreshView(TokenRefreshView):
    permission_classes = (AllowAny,)


class MeView(APIView):
    """GET -> utilisateur courant + rôle (nécessite Bearer access)."""
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        return Response(MeSerializer(request.user).data)


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
