from datetime import timedelta

from django import forms
from django.utils import timezone

from .models import LIMIT, Network
from .texts import default_text, length


class DiffusionForm(forms.Form):
    """Un bloc par réseau (case à cocher + texte), puis « maintenant » ou une date de publication."""

    when = forms.ChoiceField(label="Quand ?", choices=[("now", "Tout de suite"), ("later", "Programmer")],
                             widget=forms.RadioSelect, initial="now")
    scheduled_at = forms.DateTimeField(label="Le", required=False,
                                       widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"))

    def __init__(self, *args, event, config, **kwargs):
        super().__init__(*args, **kwargs)
        self.event, self.config = event, config
        self.networks = []
        for value, label in Network.choices:
            ready = config.network_ready(value)
            self.fields[f"on_{value}"] = forms.BooleanField(label=label, required=False, initial=ready, disabled=not ready)
            self.fields[f"text_{value}"] = forms.CharField(
                label=f"Texte {label}", required=False, initial=default_text(event, value, config.social_signature),
                widget=forms.Textarea(attrs={"rows": 9, "data-limit": LIMIT[value], "data-network": value}))
            self.networks.append((value, label, ready))

    def blocks(self):
        return [(value, label, ready, self[f"on_{value}"], self[f"text_{value}"], LIMIT[value])
                for value, label, ready in self.networks]

    def clean(self):
        data = super().clean()
        chosen = [v for v, _l, ready in self.networks if ready and data.get(f"on_{v}")]
        if not chosen:
            raise forms.ValidationError("Choisis au moins un réseau (configuré et activé dans les réglages).")
        for value in chosen:
            text = (data.get(f"text_{value}") or "").strip()
            if not text:
                self.add_error(f"text_{value}", "Texte vide.")
            elif length(value, text) > LIMIT[value]:
                self.add_error(f"text_{value}", f"Trop long : {length(value, text)} caractères pour {LIMIT[value]}.")
        if data.get("when") == "later":
            at = data.get("scheduled_at")
            if not at:
                self.add_error("scheduled_at", "Indique la date et l'heure de publication.")
            elif at < timezone.now() - timedelta(minutes=1):
                self.add_error("scheduled_at", "Cette date est passée.")
        data["chosen"] = chosen
        return data
