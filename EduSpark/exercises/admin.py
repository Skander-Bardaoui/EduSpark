from django.contrib import admin
from .models import (
    Assignment, AssignmentExercise, Category, Choice,
    Exercise, ExerciseSeries, PracticeAttempt,
    Question, Rubric, RubricCriterion, SeriesItem, StudentSubmission,
)


class ChoiceInline(admin.TabularInline):
    model = Choice
    extra = 4


class QuestionInline(admin.StackedInline):
    model = Question
    extra = 1


class CriterionInline(admin.TabularInline):
    model = RubricCriterion
    extra = 2


class SeriesItemInline(admin.TabularInline):
    model = SeriesItem
    extra = 2


class AssignmentExerciseInline(admin.TabularInline):
    model = AssignmentExercise
    extra = 2


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "university", "department", "is_active")
    list_filter = ("university", "is_active")
    search_fields = ("name", "department")


@admin.register(Exercise)
class ExerciseAdmin(admin.ModelAdmin):
    list_display = ("title", "university", "author", "exercise_type", "difficulty", "status", "usage_count")
    list_filter = ("university", "exercise_type", "difficulty", "status", "ai_generated")
    search_fields = ("title", "subject", "tags")
    inlines = [QuestionInline]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "question_type", "points")
    inlines = [ChoiceInline]


@admin.register(Rubric)
class RubricAdmin(admin.ModelAdmin):
    list_display = ("name", "university", "author", "status", "usage_count")
    list_filter = ("university", "status")
    inlines = [CriterionInline]


@admin.register(ExerciseSeries)
class ExerciseSeriesAdmin(admin.ModelAdmin):
    list_display = ("name", "university", "author", "visibility", "exercise_count")
    list_filter = ("university", "visibility")
    inlines = [SeriesItemInline]


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("title", "university", "author", "status", "deadline", "submissions_count")
    list_filter = ("university", "status")
    inlines = [AssignmentExerciseInline]


@admin.register(StudentSubmission)
class StudentSubmissionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "status", "grade", "submitted_at")
    list_filter = ("status",)


@admin.register(PracticeAttempt)
class PracticeAttemptAdmin(admin.ModelAdmin):
    list_display = ("student", "series", "score", "max_score", "result", "created_at")
    list_filter = ("result",)
