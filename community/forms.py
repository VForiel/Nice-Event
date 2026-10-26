from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.utils.translation import gettext_lazy as _

from events.models import Category, Event

from .models import Profile

User = get_user_model()


class SignupForm(forms.Form):
    display_name = forms.CharField(label=_("Prénom et nom (ou pseudo)"), max_length=80,
                                   widget=forms.TextInput(attrs={"autocomplete": "name"}))
    email = forms.EmailField(label=_("Courriel"), widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password = forms.CharField(label=_("Mot de passe"), strip=False,
                               widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                               help_text=_("Au moins 8 caractères, pas uniquement des chiffres."))
    # Piège à robots : champ masqué que les humains laissent vide.
    website = forms.CharField(required=False, label=_("Laisser vide"),
                              widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))
    consent = forms.BooleanField(label=_("J'accepte les conditions d'utilisation et la charte de publication."))

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("Un compte existe déjà avec cette adresse."))
        return email

    def clean(self):
        data = super().clean()
        if data.get("password"):
            probe = User(username=data.get("email", ""), email=data.get("email", ""), first_name=data.get("display_name", ""))
            try:
                password_validation.validate_password(data["password"], probe)
            except forms.ValidationError as error:
                self.add_error("password", error)
        return data

    def is_spam(self):
        return bool(self.cleaned_data.get("website"))

    def save(self, confirmed):
        data = self.cleaned_data
        user = User.objects.create_user(username=data["email"], email=data["email"], password=data["password"],
                                        first_name=data["display_name"].split(" ")[0][:150])
        profile = user.profile  # créé par le signal post_save
        profile.display_name = data["display_name"].strip()
        profile.handle = ""  # recalculé à partir du nom complet
        profile.email_confirmed = confirmed
        profile.save()
        return user


class LoginForm(AuthenticationForm):
    username = forms.CharField(label=_("Courriel"), widget=forms.TextInput(attrs={"autocomplete": "email", "autofocus": True}))

    error_messages = {
        "invalid_login": _("Courriel ou mot de passe incorrect."),
        "inactive": _("Ce compte est désactivé."),
    }


class PartialSaveMixin:
    """Formulaire qui s'enregistre toujours : un champ refusé est écarté et garde sa valeur précédente, les autres sont
    enregistrés. Les champs écartés et leurs erreurs sont dans `skipped` (repris de l'AJC06)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.skipped = {}
        self._before = {name: getattr(self.instance, name) for name in self.fields
                        if hasattr(self.instance, name) and name not in self._meta_m2m()}

    def _meta_m2m(self):
        return {f.name for f in self.instance._meta.many_to_many}

    def _drop_invalid(self):
        for name in [n for n in self._errors if n in self.fields]:
            self.skipped[name] = self._errors.pop(name)
            self.cleaned_data.pop(name, None)
            if name in self._before:
                setattr(self.instance, name, self._before[name])

    def _clean_fields(self):
        super()._clean_fields()
        self._drop_invalid()

    def _post_clean(self):
        super()._post_clean()
        self._drop_invalid()

    def skipped_summary(self):
        return "; ".join(f"{self.fields[name].label} ({' '.join(errors)})" for name, errors in self.skipped.items())


class ProfileForm(PartialSaveMixin, forms.ModelForm):
    spoken_list = forms.MultipleChoiceField(label=_("Langues parlées"), choices=Event.SPOKEN, required=False,
                                            widget=forms.CheckboxSelectMultiple)

    class Meta:
        model = Profile
        fields = [
            "display_name", "pronouns", "avatar", "headline", "bio", "commune", "interests", "website", "accent",
            "visibility", "show_events", "email_notifications",
            "phone", "whatsapp", "instagram", "facebook", "bluesky", "x", "other_contact", "contact_visibility",
        ]
        widgets = {
            "avatar": forms.ClearableFileInput(attrs={"accept": "image/*"}),
            "bio": forms.Textarea(attrs={"rows": 5}),
            "interests": forms.CheckboxSelectMultiple,
            "accent": forms.RadioSelect,
            "visibility": forms.RadioSelect,
            "contact_visibility": forms.RadioSelect,
            "phone": forms.TextInput(attrs={"type": "tel", "autocomplete": "tel"}),
            "whatsapp": forms.TextInput(attrs={"type": "tel"}),
        }
        help_texts = {"bio": _("Quelques lignes sur toi. Mise en forme Markdown possible.")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["website"].assume_scheme = "https"
        self.fields["interests"].queryset = Category.objects.all()
        self.fields["spoken_list"].initial = [c for c in self.instance.spoken.split(",") if c]
        self.order_fields(self.Meta.fields[:7] + ["spoken_list"])

    def clean_instagram(self):
        return handle_from(self.cleaned_data["instagram"])

    def clean_x(self):
        return handle_from(self.cleaned_data["x"])

    def clean_bluesky(self):
        return handle_from(self.cleaned_data["bluesky"])

    def save(self, commit=True):
        if "spoken_list" in self.cleaned_data:
            self.instance.spoken = ",".join(self.cleaned_data["spoken_list"])
        return super().save(commit)


def handle_from(value):
    """« @nom », « nom » ou « https://instagram.com/nom/ » donnent « nom »."""
    value = value.strip()
    if "/" in value:
        value = value.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return value.lstrip("@")


class EmailForm(forms.Form):
    email = forms.EmailField(label=_("Courriel"))

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError(_("Un compte existe déjà avec cette adresse."))
        return email


class DeleteAccountForm(forms.Form):
    password = forms.CharField(label=_("Ton mot de passe, pour confirmer"), strip=False, widget=forms.PasswordInput)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        if not self.user.check_password(self.cleaned_data["password"]):
            raise forms.ValidationError(_("Mot de passe incorrect."))
        return self.cleaned_data["password"]


class ReportForm(forms.Form):
    reason = forms.CharField(label=_("Qu'est-ce qui ne va pas ?"), max_length=1000, widget=forms.Textarea(attrs={"rows": 4}),
                             help_text=_("Arnaque, faux événement, contenu choquant ou illégal, revente de billets…"))
