from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from users.tenancy import Role


def platform_role(user):
    return Role.PLATFORM_ADMIN.value if user.is_superuser else None


class EduTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Connexion API : ajoute l'e-mail et les universités dans la réponse / le token.

    Le rôle dépend de l'université : le client choisit l'université avec
    l'en-tête « X-University: <slug ou id> » sur chaque requête.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["email"] = user.email
        token["platform_role"] = platform_role(user)
        return token

    def validate(self, attrs):
        attrs[self.username_field] = attrs.get(self.username_field, "").strip().lower()
        data = super().validate(attrs)
        data["email"] = self.user.email
        data["platform_role"] = platform_role(self.user)
        data["memberships"] = MembershipSerializer(
            self.user.memberships.filter(is_active=True).select_related("university"), many=True,
        ).data
        return data


class MembershipSerializer(serializers.Serializer):
    university_id = serializers.IntegerField(source="university.pk")
    university_slug = serializers.CharField(source="university.slug")
    university_name = serializers.CharField(source="university.name")
    role = serializers.CharField()
    is_active = serializers.BooleanField()


class MeSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    email = serializers.EmailField(read_only=True)
    first_name = serializers.CharField(read_only=True)
    last_name = serializers.CharField(read_only=True)
    bio = serializers.CharField(read_only=True)
    platform_role = serializers.SerializerMethodField()
    memberships = serializers.SerializerMethodField()

    def get_platform_role(self, user):
        return platform_role(user)

    def get_memberships(self, user):
        return MembershipSerializer(user.memberships.select_related("university"), many=True).data


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()
