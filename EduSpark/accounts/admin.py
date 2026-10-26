from django.contrib import admin

from .models import (
    Invitation,
    Membership,
    ProfessorProfile,
    Profil,
    SchoolClass,
    StudentGroup,
    StudentProfile,
    University,
)


@admin.register(Profil)
class ProfilAdmin(admin.ModelAdmin):
    list_display = ("user", "role")
    list_filter = ("role",)
    search_fields = ("user__email", "user__username", "user__first_name")


@admin.register(University)
class UniversityAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "city", "email_domain", "is_active", "created_at")
    list_filter = ("is_active", "country")
    search_fields = ("name", "code", "city", "email_domain")
    prepopulated_fields = {"slug": ("name",)}


class ProfessorProfileInline(admin.StackedInline):
    model = ProfessorProfile
    extra = 0


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "university", "role", "is_active", "created_at")
    list_filter = ("role", "is_active", "university")
    search_fields = ("user__email", "user__username", "university__name")
    autocomplete_fields = ("user",)
    inlines = (ProfessorProfileInline,)


@admin.register(ProfessorProfile)
class ProfessorProfileAdmin(admin.ModelAdmin):
    list_display = ("membership", "department", "speciality", "grade")
    list_filter = ("grade", "university")
    search_fields = ("membership__user__email", "membership__user__last_name", "department", "speciality")


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("membership", "student_number", "program", "level", "section", "promotion")
    list_filter = ("university", "level", "section")
    search_fields = (
        "membership__user__email", "membership__user__last_name",
        "student_number", "program", "level", "section",
    )


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ("name", "university", "level", "section", "program", "academic_year")
    list_filter = ("university", "academic_year")
    search_fields = ("name", "program", "level", "section")
    filter_horizontal = ("professors",)


@admin.register(StudentGroup)
class StudentGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "school_class", "university", "capacity")
    list_filter = ("university", "school_class")
    search_fields = ("name", "school_class__name")
    filter_horizontal = ("students",)


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "university", "role", "status", "expires_at", "created_at")
    list_filter = ("status", "role", "university")
    search_fields = ("email", "university__name")
    readonly_fields = ("token", "accepted_at", "created_at")
