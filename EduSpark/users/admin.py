from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    Invitation, Membership, ProfessorProfile, SchoolClass, StudentGroup, StudentProfile, University, User,
)


class TenantAdminMixin:
    """Une ligne enregistrée ne change jamais d'université (cf. TenantModel)."""

    tenant_readonly_on_change = ("university",)

    def get_readonly_fields(self, request, obj=None):
        fields = tuple(super().get_readonly_fields(request, obj))
        return fields + self.tenant_readonly_on_change if obj is not None else fields


class MembershipInline(admin.TabularInline):
    """Consultation des appartenances depuis la fiche utilisateur ; l'ajout et la
    modification passent par l'admin Appartenances (université figée après création)."""

    model = Membership
    fk_name = "user"
    extra = 0
    fields = ("university", "role", "is_active", "awaiting_email_verification")
    readonly_fields = fields
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "first_name", "last_name", "email_verified", "is_superuser", "is_active")
    list_filter = ("is_superuser", "is_active", "email_verified", "memberships__role", "memberships__university")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)
    fieldsets = BaseUserAdmin.fieldsets + (("Profil EduSpark", {"fields": ("email_verified", "phone", "bio")}),)
    inlines = (MembershipInline,)


@admin.register(University)
class UniversityAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "city", "country", "email_domain", "is_active")
    list_filter = ("is_active", "country")
    search_fields = ("name", "code", "city")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Membership)
class MembershipAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("user", "university", "role", "is_active", "awaiting_email_verification", "created_at")
    list_filter = ("university", "role", "is_active", "awaiting_email_verification")
    search_fields = ("user__email", "user__first_name", "user__last_name")
    autocomplete_fields = ("user", "university")


class ProfileAdminMixin(TenantAdminMixin):
    """L'université d'un profil vient toujours de son appartenance."""

    tenant_readonly_on_change = ("membership",)
    exclude = ("university",)


@admin.register(ProfessorProfile)
class ProfessorProfileAdmin(ProfileAdminMixin, admin.ModelAdmin):
    list_display = ("__str__", "university", "department", "speciality", "grade")
    list_filter = ("university", "grade")
    search_fields = ("membership__user__email", "membership__user__last_name", "department", "speciality")


@admin.register(StudentProfile)
class StudentProfileAdmin(ProfileAdminMixin, admin.ModelAdmin):
    list_display = ("__str__", "university", "student_number", "program", "promotion")
    list_filter = ("university", "program", "promotion")
    search_fields = ("membership__user__email", "membership__user__last_name", "student_number")


class StudentGroupInline(admin.TabularInline):
    model = StudentGroup
    extra = 0
    exclude = ("university", "students")


class SchoolClassAdminForm(forms.ModelForm):
    class Meta:
        model = SchoolClass
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        university = cleaned.get("university") or getattr(self.instance, "university", None)
        foreign = [p for p in cleaned.get("professors") or [] if university and p.university_id != university.pk]
        if foreign:
            self.add_error("professors", "Ces professeurs appartiennent à une autre université : "
                           + ", ".join(str(p) for p in foreign))
        return cleaned


@admin.register(SchoolClass)
class SchoolClassAdmin(TenantAdminMixin, admin.ModelAdmin):
    form = SchoolClassAdminForm
    list_display = ("name", "university", "level", "program", "academic_year")
    list_filter = ("university", "academic_year", "level")
    search_fields = ("name", "program")
    inlines = (StudentGroupInline,)


@admin.register(Invitation)
class InvitationAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ("email", "university", "role", "status", "expires_at", "invited_by")
    list_filter = ("university", "role", "status")
    search_fields = ("email",)
    readonly_fields = ("token", "accepted_by", "accepted_at")
