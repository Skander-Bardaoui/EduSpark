from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from ..forms import SchoolClassForm, StudentGroupForm
from ..models import SchoolClass, StudentGroup
from ..tenancy import Role, TenantScopedMixin
from .mixins import GenericDeleteMixin, GenericFormMixin, SearchFilterMixin, SuccessMessageMixin, distinct_choices

ADMIN = (Role.UNIVERSITY_ADMIN,)


class SchoolClassListView(TenantScopedMixin, SearchFilterMixin, ListView):
    """Tous les membres consultent ; seul l'admin université modifie."""

    model = SchoolClass
    template_name = "users/classes/list.html"
    context_object_name = "classes"
    search_fields = ("name", "program", "level", "description")
    search_placeholder = "Nom, filière, niveau…"

    def get_queryset(self):
        return super().get_queryset().prefetch_related("groups__students", "professors__membership__user")

    def get_filters(self):
        base = SchoolClass.objects.filter(university=self.request.university)
        return [
            {"param": "niveau", "lookup": "level", "label": "Niveau", "choices": distinct_choices(base, "level")},
            {"param": "filiere", "lookup": "program", "label": "Filière", "choices": distinct_choices(base, "program")},
            {"param": "annee", "lookup": "academic_year", "label": "Année",
             "choices": distinct_choices(base, "academic_year")},
        ]


class SchoolClassDetailView(TenantScopedMixin, DetailView):
    model = SchoolClass
    template_name = "users/classes/detail.html"
    context_object_name = "school_class"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["groups"] = self.object.groups.prefetch_related("students__membership__user")
        context["professors"] = self.object.professors.select_related("membership__user")
        return context


class _SchoolClassFormMixin(TenantScopedMixin, GenericFormMixin, SuccessMessageMixin):
    model = SchoolClass
    form_class = SchoolClassForm
    allowed_roles = ADMIN
    page_icon = "groups"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["university"] = self.request.university
        return kwargs

    def get_success_url(self):
        return reverse("users:class_detail", args=[self.object.pk])


class SchoolClassCreateView(_SchoolClassFormMixin, CreateView):
    page_title = "Nouvelle classe"
    submit_label = "Créer la classe"
    cancel_url = reverse_lazy("users:class_list")
    success_message = "Classe créée."


class SchoolClassUpdateView(_SchoolClassFormMixin, UpdateView):
    success_message = "Classe mise à jour."

    def get_context_data(self, **kwargs):
        self.page_title = f"Modifier — {self.object}"
        return super().get_context_data(**kwargs)


class SchoolClassDeleteView(TenantScopedMixin, GenericDeleteMixin, DeleteView):
    model = SchoolClass
    allowed_roles = ADMIN
    success_url = reverse_lazy("users:class_list")
    delete_title = "Supprimer la classe"
    delete_warning = "La classe et tous ses groupes seront supprimés (les étudiants sont conservés)."
    success_message = "Classe supprimée."


# --- Groupes (toujours rattachés à une classe de l'université courante) -------

class _GroupMixin(TenantScopedMixin):
    model = StudentGroup
    allowed_roles = ADMIN

    def get_school_class(self):
        return get_object_or_404(SchoolClass, pk=self.kwargs["class_pk"], university=self.request.university)

    def get_queryset(self):
        return super().get_queryset().filter(school_class_id=self.kwargs["class_pk"])

    def get_success_url(self):
        return reverse("users:class_detail", args=[self.kwargs["class_pk"]])

    def get_cancel_url(self):
        return self.get_success_url()


class _GroupFormMixin(_GroupMixin, GenericFormMixin, SuccessMessageMixin):
    form_class = StudentGroupForm
    page_icon = "diversity_3"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["school_class"] = self.get_school_class()
        return kwargs


class StudentGroupCreateView(_GroupFormMixin, CreateView):
    submit_label = "Créer le groupe"
    success_message = "Groupe créé."

    def get_context_data(self, **kwargs):
        self.page_title = f"Nouveau groupe — {self.get_school_class()}"
        return super().get_context_data(**kwargs)

    def form_valid(self, form):
        form.instance.school_class = self.get_school_class()
        return super().form_valid(form)


class StudentGroupUpdateView(_GroupFormMixin, UpdateView):
    success_message = "Groupe mis à jour."

    def get_context_data(self, **kwargs):
        self.page_title = f"Modifier le groupe — {self.object}"
        return super().get_context_data(**kwargs)


class StudentGroupDeleteView(_GroupMixin, GenericDeleteMixin, DeleteView):
    delete_title = "Supprimer le groupe"
    delete_warning = "Le groupe sera supprimé ; les étudiants restent inscrits dans l'université."
    success_message = "Groupe supprimé."
