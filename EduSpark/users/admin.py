from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    Invitation, Membership, ProfessorProfile, SchoolClass, StudentGroup, StudentProfile, University, User,
)


class MembershipInline(admin.TabularInline):
    model = Membership
    fk_name = "user"
    extra = 0
    autocomplete_fields = ("university",)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "first_name", "last_name", "is_superuser", "is_active")
    list_filter = ("is_superuser", "is_active", "memberships__role", "memberships__university")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)
    fieldsets = BaseUserAdmin.fieldsets + (("Profil EduSpark", {"fields": ("phone", "bio")}),)
    inlines = (MembershipInline,)


@admin.register(University)
class UniversityAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "city", "country", "email_domain", "is_active")
    list_filter = ("is_active", "country")
    search_fields = ("name", "code", "city")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "university", "role", "is_active", "created_at")
    list_filter = ("university", "role", "is_active")
    search_fields = ("user__email", "user__first_name", "user__last_name")
    autocomplete_fields = ("user", "university")


@admin.register(ProfessorProfile)
class ProfessorProfileAdmin(admin.ModelAdmin):
    list_display = ("__str__", "university", "department", "speciality", "grade")
    list_filter = ("university", "grade")
    search_fields = ("membership__user__email", "membership__user__last_name", "department", "speciality")


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("__str__", "university", "student_number", "program", "promotion")
    list_filter = ("university", "program", "promotion")
    search_fields = ("membership__user__email", "membership__user__last_name", "student_number")


class StudentGroupInline(admin.TabularInline):
    model = StudentGroup
    extra = 0
    exclude = ("university", "students")


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ("name", "university", "level", "program", "academic_year")
    list_filter = ("university", "academic_year", "level")
    search_fields = ("name", "program")
    inlines = (StudentGroupInline,)


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "university", "role", "status", "expires_at", "invited_by")
    list_filter = ("university", "role", "status")
    search_fields = ("email",)
    readonly_fields = ("token", "accepted_by", "accepted_at")
