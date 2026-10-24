"""Briques communes aux pages de gestion : recherche, filtres, pagination,
messages de succès et envoi du lien « définir mon mot de passe »."""

from django.contrib import messages
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db.models import Q
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_encode


def redirect_next(request, default, *args, **kwargs):
    """Redirige vers ?next= / POST next s'il est local, sinon vers default."""
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect(default, *args, **kwargs)


class SearchFilterMixin:
    """ListView avec recherche plein texte (?q=) et filtres (?<param>=).

    search_fields : champs interrogés en icontains.
    get_filters() : liste de dicts {param, lookup, label, choices[, bool]}.
    """

    search_fields = ()
    search_placeholder = "Rechercher…"
    paginate_by = 15

    def get_filters(self):
        return []

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get("q", "").strip()
        if q and self.search_fields:
            condition = Q()
            for field in self.search_fields:
                condition |= Q(**{f"{field}__icontains": q})
            qs = qs.filter(condition)
        valid = {}
        for spec in self.get_filters():
            value = self.request.GET.get(spec["param"], "")
            allowed = {str(v) for v, _label in spec["choices"]}
            if value == "" or value not in allowed:
                continue
            valid[spec["param"]] = value
            qs = qs.filter(**{spec["lookup"]: (value == "1") if spec.get("bool") else value})
        self.active_filters = valid
        return qs.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        filters = []
        for spec in self.get_filters():
            filters.append({**spec, "current": self.request.GET.get(spec["param"], "")})
        context.update({
            "q": self.request.GET.get("q", ""),
            "filters": filters,
            "search_placeholder": self.search_placeholder,
            "querystring": params.urlencode(),
            "is_filtered": bool(self.request.GET.get("q")) or bool(getattr(self, "active_filters", None)),
        })
        return context


def distinct_choices(queryset, field):
    """Choix de filtre construits à partir des valeurs existantes."""
    values = queryset.exclude(**{field: ""}).order_by(field).values_list(field, flat=True).distinct()
    return [(v, v) for v in values]


class SuccessMessageMixin:
    success_message = ""

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.success_message:
            messages.success(self.request, self.success_message)
        return response


class GenericFormMixin:
    """Contexte du template générique users/generic/form.html."""

    template_name = "users/generic/form.html"
    page_title = ""
    page_icon = "edit_note"
    submit_label = "Enregistrer"
    cancel_url = None

    def get_cancel_url(self):
        return self.cancel_url or self.request.META.get("HTTP_REFERER") or reverse("users:dashboard")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "page_title": self.page_title,
            "page_icon": self.page_icon,
            "submit_label": self.submit_label,
            "cancel_url": self.get_cancel_url(),
        })
        return context


class GenericDeleteMixin:
    """Page de confirmation générique users/generic/confirm_delete.html."""

    template_name = "users/generic/confirm_delete.html"
    delete_title = "Supprimer"
    delete_warning = "Cette action est définitive."
    success_message = "Élément supprimé."

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "delete_title": self.delete_title,
            "delete_warning": self.delete_warning,
            "cancel_url": self.request.META.get("HTTP_REFERER") or reverse("users:dashboard"),
        })
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, self.success_message)
        return response


def send_set_password_email(request, user, university):
    """Envoie au nouveau membre un lien pour choisir son mot de passe."""
    link = request.build_absolute_uri(reverse("users:password_reset_confirm", kwargs={
        "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
        "token": default_token_generator.make_token(user),
    }))
    body = render_to_string("users/emails/welcome_member.txt", {
        "user": user, "university": university, "link": link,
    })
    send_mail(f"Votre compte EduSpark — {university.name}", body, None, [user.email], fail_silently=True)


def send_invitation_email(request, invitation):
    link = request.build_absolute_uri(reverse("users:invitation_accept", kwargs={"token": invitation.token}))
    body = render_to_string("users/emails/invitation.txt", {"invitation": invitation, "link": link})
    send_mail(
        f"Invitation à rejoindre {invitation.university.name} sur EduSpark",
        body, None, [invitation.email], fail_silently=True,
    )
