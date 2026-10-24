"""Comptes utilisateurs — vue globale réservée à l'admin plateforme.

Les admins université, eux, gèrent leurs membres via professeurs / étudiants.
"""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import DeleteView, DetailView, ListView, UpdateView

from ..forms import AccountForm
from ..models import Membership, University
from ..tenancy import MEMBERSHIP_ROLES, PlatformAdminRequiredMixin
from .mixins import GenericDeleteMixin, GenericFormMixin, SearchFilterMixin, SuccessMessageMixin

User = get_user_model()


class AccountListView(PlatformAdminRequiredMixin, SearchFilterMixin, ListView):
    model = User
    template_name = "users/accounts/list.html"
    context_object_name = "accounts"
    search_fields = ("first_name", "last_name", "email")
    search_placeholder = "Nom, prénom, e-mail…"

    def get_queryset(self):
        return super().get_queryset().prefetch_related("memberships__university")

    def get_filters(self):
        return [
            {"param": "role", "lookup": "memberships__role", "label": "Rôle", "choices": MEMBERSHIP_ROLES},
            {"param": "universite", "lookup": "memberships__university", "label": "Université",
             "choices": [(str(u.pk), u.name) for u in University.objects.all()]},
            {"param": "admin", "lookup": "is_superuser", "label": "Admin plateforme", "bool": True,
             "choices": [("1", "Oui"), ("0", "Non")]},
            {"param": "statut", "lookup": "is_active", "label": "Statut", "bool": True,
             "choices": [("1", "Actif"), ("0", "Désactivé")]},
        ]


class AccountDetailView(PlatformAdminRequiredMixin, DetailView):
    model = User
    template_name = "users/accounts/detail.html"
    context_object_name = "account"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["memberships"] = Membership.objects.filter(user=self.object).select_related("university")
        return context


class AccountUpdateView(PlatformAdminRequiredMixin, GenericFormMixin, SuccessMessageMixin, UpdateView):
    model = User
    form_class = AccountForm
    page_icon = "manage_accounts"
    success_message = "Compte mis à jour."

    def get_context_data(self, **kwargs):
        self.page_title = f"Modifier le compte — {self.object.display_name}"
        return super().get_context_data(**kwargs)

    def form_valid(self, form):
        if self.object == self.request.user and not form.cleaned_data["is_platform_admin"]:
            form.add_error("is_platform_admin", "Vous ne pouvez pas retirer vos propres droits d'admin plateforme.")
            return self.form_invalid(form)
        return super().form_valid(form)

    def get_cancel_url(self):
        return reverse("users:account_detail", args=[self.object.pk])

    def get_success_url(self):
        return reverse("users:account_detail", args=[self.object.pk])


class AccountDeleteView(PlatformAdminRequiredMixin, GenericDeleteMixin, DeleteView):
    model = User
    success_url = reverse_lazy("users:account_list")
    delete_title = "Supprimer le compte"
    delete_warning = "Le compte et toutes ses appartenances aux universités seront supprimés."
    success_message = "Compte supprimé."

    def form_valid(self, form):
        if self.object == self.request.user:
            messages.error(self.request, "Vous ne pouvez pas supprimer votre propre compte.")
            return redirect("users:account_detail", pk=self.object.pk)
        return super().form_valid(form)
