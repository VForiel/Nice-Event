from django import forms

from .models import SiteConfig

# Champs secrets : jamais réaffichés ; vide = on garde la valeur enregistrée, case « effacer » pour la supprimer.
SECRETS = ["smtp_password"]


class SecretInput(forms.PasswordInput):
    def __init__(self, attrs=None):
        super().__init__(attrs={"autocomplete": "new-password", **(attrs or {})}, render_value=False)


class SiteConfigForm(forms.ModelForm):
    clear_smtp_password = forms.BooleanField(label="Effacer le mot de passe enregistré", required=False)

    class Meta:
        model = SiteConfig
        fields = ["smtp_host", "smtp_port", "smtp_security", "smtp_user", "smtp_password", "from_email", "contact_email",
                  "require_email_confirmation"]
        widgets = {"smtp_password": SecretInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in SECRETS:
            field = self.fields[name]
            field.required = False
            stored = bool(getattr(self.instance, name))
            field.help_text = "Enregistré ; laisser vide pour le conserver." if stored else "Aucun enregistré."
            field.widget.attrs["placeholder"] = "••••••••" if stored else ""

    def clean(self):
        data = super().clean()
        for name in SECRETS:
            if self.cleaned_data.get(f"clear_{name}"):
                data[name] = ""
            elif not data.get(name):
                data[name] = getattr(self.instance, name)  # rien saisi : on garde l'ancien
        return data

    def changed_labels(self, before):
        """Libellés des réglages réellement modifiés (pour le journal, sans les valeurs) ; `before` : {champ: valeur}
        relevé avant l'enregistrement."""
        return [str(self.fields[n].label) for n in self.Meta.fields if before[n] != getattr(self.instance, n)]


def snapshot(config):
    return {n: getattr(config, n) for n in SiteConfigForm.Meta.fields}


class TestEmailForm(forms.Form):
    to = forms.EmailField(label="Envoyer un courriel de test à")
