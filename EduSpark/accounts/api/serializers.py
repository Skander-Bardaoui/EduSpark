from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from accounts.decorators import get_user_role


class EduTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Connexion API : ajoute le rôle et l'e-mail dans la réponse / le token."""

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = get_user_role(user)
        token["email"] = user.email
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["role"] = get_user_role(self.user)
        data["email"] = self.user.email
        return data


class MeSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    email = serializers.EmailField(read_only=True)
    first_name = serializers.CharField(read_only=True)
    role = serializers.SerializerMethodField()
    groups = serializers.SerializerMethodField()

    def get_role(self, user):
        return get_user_role(user)

    def get_groups(self, user):
        return sorted(g.name for g in user.groups.all())


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()
