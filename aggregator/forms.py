from django import forms
from django.utils.text import slugify

from .models import Source


class SourceForm(forms.ModelForm):
    clear_api_key = forms.BooleanField(label="Effacer la clé enregistrée", required=False)

    class Meta:
        model = Source
        fields = ["name", "kind", "url", "website", "api_key", "is_active", "default_category", "default_commune",
                  "max_pages", "link_pattern", "title_pattern", "default_place", "images_allowed", "notes"]
        widgets = {"api_key": forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
                   "notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["api_key"].required = False
        if self.instance.api_key:
            self.fields["api_key"].help_text = "Enregistrée ; laisser vide pour la conserver."
        self.fields["default_commune"].queryset = self.fields["default_commune"].queryset.order_by("-population")

    def clean_title_pattern(self):
        return self.clean_regex("title_pattern")

    def clean_link_pattern(self):
        return self.clean_regex("link_pattern")

    def clean_regex(self, name):
        import re

        value = self.cleaned_data[name].strip()
        try:
            re.compile(value)
        except re.error as exc:
            raise forms.ValidationError(f"Expression régulière invalide : {exc}")
        return value

    def clean(self):
        data = super().clean()
        if self.cleaned_data.get("clear_api_key"):
            data["api_key"] = ""
        elif not data.get("api_key"):
            data["api_key"] = self.instance.api_key
        if data.get("kind") == Source.Kind.OPENAGENDA and not data.get("api_key"):
            self.add_error("api_key", "OpenAgenda demande une clé d'API (compte OpenAgenda › Paramètres › Clé API).")
        return data

    def save(self, commit=True):
        if not self.instance.slug:
            base, n = slugify(self.cleaned_data["name"])[:45] or "source", 2
            slug = base
            while Source.objects.filter(slug=slug).exclude(pk=self.instance.pk).exists():
                slug, n = f"{base}-{n}", n + 1
            self.instance.slug = slug
        return super().save(commit)
