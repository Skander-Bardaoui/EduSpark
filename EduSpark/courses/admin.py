from django.contrib import admin

from .models import (
    Chapter, Course, CourseMaterial, CoursePublication, Department, Program,
    ScheduleSlot, Subject, TeachingAssignment,
)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "university", "head")
    list_filter = ("university",)
    search_fields = ("name", "code")
    autocomplete_fields = ("head",)


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "department", "degree", "duration_years", "university")
    list_filter = ("university", "degree")
    search_fields = ("name", "code", "department__name")
    autocomplete_fields = ("department", "coordinator")


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "program", "semester", "coefficient", "credits", "is_active", "university")
    list_filter = ("university", "is_active", "semester")
    search_fields = ("code", "name", "program__name")
    autocomplete_fields = ("program",)


@admin.register(TeachingAssignment)
class TeachingAssignmentAdmin(admin.ModelAdmin):
    list_display = ("school_class", "subject", "professor", "university")
    list_filter = ("university",)
    search_fields = (
        "school_class__name", "subject__code", "subject__name",
        "professor__membership__user__last_name", "professor__membership__user__email",
    )
    autocomplete_fields = ("school_class", "subject", "professor")


@admin.register(ScheduleSlot)
class ScheduleSlotAdmin(admin.ModelAdmin):
    list_display = ("assignment", "session_type", "weekday", "start_time", "end_time", "room", "group")
    list_filter = ("university", "weekday", "session_type")
    search_fields = ("assignment__subject__name", "assignment__school_class__name", "room")
    autocomplete_fields = ("assignment", "group")


class ChapterInline(admin.TabularInline):
    model = Chapter
    extra = 0


class CoursePublicationInline(admin.TabularInline):
    model = CoursePublication
    extra = 0
    autocomplete_fields = ("school_class",)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "subject", "professor", "university", "updated_at")
    list_filter = ("university",)
    search_fields = ("title", "subject__name", "subject__code")
    autocomplete_fields = ("subject", "professor")
    inlines = (ChapterInline, CoursePublicationInline)


@admin.register(CoursePublication)
class CoursePublicationAdmin(admin.ModelAdmin):
    list_display = ("course", "school_class", "is_published", "published_at")
    list_filter = ("university", "is_published")
    search_fields = ("course__title", "school_class__name")


@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "order")
    search_fields = ("title", "course__title")
    autocomplete_fields = ("course",)


@admin.register(CourseMaterial)
class CourseMaterialAdmin(admin.ModelAdmin):
    list_display = ("title", "course", "material_type", "size", "uploaded_by", "created_at")
    list_filter = ("material_type",)
    search_fields = ("title", "original_name", "course__title")
    readonly_fields = ("material_type", "original_name", "size", "uploaded_by")
    autocomplete_fields = ("course", "chapter")
