from django import forms
from django.utils.translation import gettext_lazy as _

from .models import SUBJECTS, ContactMessage


class ContactForm(forms.ModelForm):
    subject = forms.ChoiceField(label=_("C'est à propos de"), choices=SUBJECTS, widget=forms.RadioSelect, initial="question")
    # Piège à robots : champ masqué que les humains laissent vide.
    website = forms.CharField(required=False, label=_("Laisser vide"), widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))
    consent = forms.BooleanField(label=_("J'accepte que Nice-Event utilise ces informations pour me répondre, et pour rien d'autre."))

    class Meta:
        model = ContactMessage
        fields = ["name", "email", "subject", "message"]
        labels = {"name": _("Ton nom"), "email": _("Ton courriel"), "message": _("Ton message")}
        widgets = {
            "name": forms.TextInput(attrs={"autocomplete": "name"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "message": forms.Textarea(attrs={"rows": 6}),
        }

    def is_spam(self):
        return bool(self.cleaned_data.get("website"))
