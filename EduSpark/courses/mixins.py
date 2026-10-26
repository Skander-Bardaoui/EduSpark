"""Briques communes aux vues du module cours : accès par rôle, pages de
formulaire et de suppression aux couleurs du portail de l'utilisateur."""

from django.contrib import messages
from django.db.models import ProtectedError, RestrictedError
from django.shortcuts import get_object_or_404, redirect
from django.utils.functional import cached_property

from accounts.models import SchoolClass
from accounts.tenancy import Role, TenantRequiredMixin, TenantScopedMixin
from accounts.view_mixins import GenericDeleteMixin, GenericFormMixin

from .services import describe_blockers

ADMIN = (Role.UNIVERSITY_ADMIN,)
PROFESSOR = (Role.PROFESSOR,)
STUDENT = (Role.STUDENT,)


class AdminMixin(TenantScopedMixin):
    """Admin de l'université courante ; les querysets sont bornés à cette université."""

    allowed_roles = ADMIN


class ProfessorMixin(TenantRequiredMixin):
    """Professeur de l'université courante (le queryset est filtré par chaque vue)."""

    allowed_roles = PROFESSOR

    @cached_property
    def professor(self):
        return self.request.membership.ensure_profile()


class StudentMixin(TenantRequiredMixin):
    allowed_roles = STUDENT

    @cached_property
    def student(self):
        return self.request.membership.ensure_profile()


class FormPageMixin(GenericFormMixin):
    """Page de formulaire (création / modification) du module cours."""

    template_name = "courses/form.html"
    eyebrow = "Cours & Catalogue"
    page_hint = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"eyebrow": self.eyebrow, "page_hint": self.page_hint})
        return context


class DeletePageMixin(GenericDeleteMixin):
    """Confirmation de suppression ; une suppression refusée (objets liés
    protégés ou restreints) devient un message d'erreur et non une erreur 500."""

    template_name = "courses/confirm_delete.html"
    eyebrow = "Cours & Catalogue"
    protected_hint = "Supprimez-les ou déplacez-les d'abord."
    cancel_url = None

    def get_cancel_url(self):
        return str(self.cancel_url) if self.cancel_url else super().get_cancel_url()

    def get_blockers(self):
        """Éléments liés affichés avant confirmation : ``[(libellé, nombre)]``."""
        return []

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "eyebrow": self.eyebrow,
            "blockers": [(label, count) for label, count in self.get_blockers() if count],
        })
        return context

    def form_valid(self, form):
        try:
            return super().form_valid(form)
        except (ProtectedError, RestrictedError) as error:
            messages.error(
                self.request,
                "Suppression impossible : %s en dépendent. %s"
                % (describe_blockers(error), self.protected_hint),
            )
            return redirect(self.get_cancel_url())


class SelectedClassMixin:
    """Classe de l'université courante passée en paramètre ``?classe=`` (facultative)."""

    def get_selected_class(self):
        if not hasattr(self, "_selected_class"):
            pk = self.request.GET.get("classe", "")
            self._selected_class = (
                get_object_or_404(SchoolClass, pk=int(pk), university=self.request.university)
                if pk.isdigit() else None
            )
        return self._selected_class
