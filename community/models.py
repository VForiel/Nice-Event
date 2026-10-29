"""Espace membres : profils, amitiés, « J'y vais », notifications et signalements (repris de l'AJC06)."""

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from core import markdown
from core.images import normalize_field, validate_image

AVATAR_SIDE = 600


class Profile(models.Model):
    # Couleurs du profil (classes CSS accent-*, pas de style en ligne : CSP).
    class Accent(models.TextChoices):
        CHAISE = "chaise", _("Bleu chaise")
        CORAIL = "corail", _("Corail")
        SOLEIL = "soleil", _("Soleil")
        OCRE = "ocre", _("Ocre")
        PIN = "pin", _("Pin parasol")
        LAVANDE = "lavande", _("Lavande")

    class Visibility(models.TextChoices):
        MEMBERS = "membres", _("Membres connectés uniquement")
        PUBLIC = "public", _("Tout le monde")

    class ContactVisibility(models.TextChoices):
        FRIENDS = "amis", _("Mes amis uniquement")
        MEMBERS = "membres", _("Tous les membres connectés")
        NOBODY = "personne", _("Personne")

    class PastVisibility(models.TextChoices):
        PROFILE = "profil", _("Tous ceux qui voient mon profil")
        FRIENDS = "amis", _("Mes amis uniquement")
        ME = "moi", _("Moi seul·e")

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    handle = models.SlugField(_("adresse du profil"), unique=True, max_length=60)
    display_name = models.CharField(_("nom affiché"), max_length=80)
    pronouns = models.CharField(_("pronoms"), max_length=30, blank=True)
    avatar = models.ImageField(_("photo"), upload_to="membres/", blank=True, validators=[validate_image])
    headline = models.CharField(_("en ce moment"), max_length=120, blank=True,
                                help_text=_("Une ligne : « Nouvelle à Nice, je cherche des sorties ! », « Fan de jazz »…"))
    bio = models.TextField(_("présentation"), blank=True)
    interests = models.ManyToManyField("events.Category", blank=True, related_name="+", verbose_name=_("ce qui me plaît"))
    spoken = models.CharField(_("langues parlées"), max_length=60, blank=True)
    commune = models.ForeignKey("venues.Commune", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                verbose_name=_("ma commune"))
    website = models.URLField(_("site web"), blank=True)
    accent = models.CharField(_("couleur du profil"), max_length=10, choices=Accent.choices, default=Accent.CHAISE)
    visibility = models.CharField(_("qui peut voir mon profil"), max_length=10, choices=Visibility.choices,
                                  default=Visibility.MEMBERS)
    show_events = models.BooleanField(_("afficher les événements à venir auxquels je participe"), default=True)
    past_events = models.CharField(_("qui voit les événements auxquels j'ai participé"), max_length=10,
                                   choices=PastVisibility.choices, default=PastVisibility.PROFILE)
    email_notifications = models.BooleanField(_("recevoir par courriel les invitations et les changements des événements où je vais"),
                                              default=True)
    # Faux tant que le lien de confirmation n'a pas été ouvert (le compte reste alors inactif).
    email_confirmed = models.BooleanField("adresse confirmée", default=True)
    # Membre de confiance : publie sans modération préalable (acquis quand l'équipe valide un premier événement).
    trusted = models.BooleanField("de confiance", default=False)
    # Coordonnées : jamais publiques, visibles selon contact_visibility.
    phone = models.CharField(_("téléphone"), max_length=30, blank=True)
    whatsapp = models.CharField("WhatsApp", max_length=30, blank=True, help_text=_("Numéro, si différent du téléphone"))
    instagram = models.CharField("Instagram", max_length=60, blank=True, help_text=_("Identifiant, sans @"))
    facebook = models.CharField("Facebook", max_length=120, blank=True, help_text=_("Identifiant ou lien du profil"))
    bluesky = models.CharField("Bluesky", max_length=80, blank=True, help_text=_("Identifiant, ex. nom.bsky.social"))
    x = models.CharField("X", max_length=60, blank=True, help_text=_("Identifiant, sans @"))
    other_contact = models.CharField(_("autre"), max_length=200, blank=True,
                                     help_text=_("Discord, Signal, Mastodon… avec le nom du réseau"))
    contact_visibility = models.CharField(_("qui peut voir mes coordonnées"), max_length=10,
                                          choices=ContactVisibility.choices, default=ContactVisibility.FRIENDS)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_name"]
        verbose_name = "profil"

    def __str__(self):
        return self.display_name

    def save(self, *args, **kwargs):
        if not self.handle:
            base = slugify(self.display_name)[:50] or "membre"
            handle, n = base, 2
            while Profile.objects.filter(handle=handle).exclude(pk=self.pk).exists():
                handle, n = f"{base}-{n}", n + 1
            self.handle = handle
        normalize_field(self, "avatar", max_side=AVATAR_SIDE)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("community:profile", args=[self.handle])

    @property
    def initials(self):
        return "".join(p[0] for p in self.display_name.replace("-", " ").split()[:2]).upper() or "?"

    @property
    def bio_html(self):
        return markdown.render(self.bio)

    @property
    def spoken_labels(self):
        from events.models import Event

        names = dict(Event.SPOKEN)
        return [str(names[c]) for c in self.spoken.split(",") if c in names]

    def visible_to(self, user):
        return self.visibility == self.Visibility.PUBLIC or user.is_authenticated

    @property
    def has_contacts(self):
        return any((self.phone, self.whatsapp, self.instagram, self.facebook, self.bluesky, self.x, self.other_contact))

    def contacts_visible_to(self, user, rel):
        if rel == "self":
            return True
        if not user.is_authenticated or self.contact_visibility == self.ContactVisibility.NOBODY:
            return False
        return self.contact_visibility == self.ContactVisibility.MEMBERS or rel == "friends"

    def past_events_visible_to(self, rel):
        if rel == "self" or self.past_events == self.PastVisibility.PROFILE:
            return True
        return self.past_events == self.PastVisibility.FRIENDS and rel == "friends"

    @property
    def whatsapp_link(self):
        digits = "".join(c for c in (self.whatsapp or self.phone) if c.isdigit())
        if digits.startswith("0") and len(digits) == 10:  # numéro français sans indicatif
            digits = "33" + digits[1:]
        return f"https://wa.me/{digits}" if digits else ""


class FriendshipQuerySet(models.QuerySet):
    def between(self, a, b):
        return self.filter(Q(from_user=a, to_user=b) | Q(from_user=b, to_user=a))


class Friendship(models.Model):
    """Demande d'amitié de from_user vers to_user ; acceptée, elle vaut dans les deux sens."""

    from_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="friend_requests_sent")
    to_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="friend_requests_received")
    accepted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = FriendshipQuerySet.as_manager()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["from_user", "to_user"], name="unique_friend_request")]
        verbose_name = "amitié"

    def __str__(self):
        return f"{self.from_user} → {self.to_user} ({'acceptée' if self.accepted else 'en attente'})"


def friend_ids(user):
    links = Friendship.objects.filter(accepted=True).filter(Q(from_user=user) | Q(to_user=user))
    return {f.to_user_id if f.from_user_id == user.pk else f.from_user_id for f in links}


def friends_of(user):
    """Utilisateurs liés à `user` par une amitié acceptée."""
    from django.contrib.auth import get_user_model

    return get_user_model().objects.filter(pk__in=friend_ids(user), is_active=True).select_related("profile")


def relation(user, other):
    """« self », « friends », « sent » (demande envoyée), « received » (à accepter), « none » ou « anonymous »."""
    if not user.is_authenticated:
        return "anonymous"
    if user.pk == other.pk:
        return "self"
    link = Friendship.objects.between(user, other).first()
    if not link:
        return "none"
    if link.accepted:
        return "friends"
    return "sent" if link.from_user_id == user.pk else "received"


class Attendance(models.Model):
    """« J'y vais » d'un membre pour un événement du site."""

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="attendances")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attendances")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["event", "user"], name="unique_attendance")]
        ordering = ["created_at"]
        verbose_name = "participation"


class EventInterest(models.Model):
    """« Ça m'intéresse » ou « Pas pour moi » d'un membre sur un événement (du site ou repris d'un agenda) :
    affiché sur le profil et utilisé par les recommandations (events.recommend)."""

    class Value(models.IntegerChoices):
        YES = 1, _("Ça m'intéresse")
        NO = -1, _("Pas pour moi")

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="interests")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="event_interests")
    value = models.SmallIntegerField(choices=Value.choices)
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["event", "user"], name="unique_event_interest")]
        ordering = ["-created_at"]
        verbose_name = "intérêt"


class Notification(models.Model):
    class Verb(models.TextChoices):
        FRIEND_REQUEST = "friend_request", "demande d'ami"
        FRIEND_ACCEPTED = "friend_accepted", "amitié acceptée"
        INVITE = "invite", "invitation"
        ATTENDING = "attending", "participation à mon événement"
        APPROVED = "approved", "événement validé"
        REJECTED = "rejected", "événement refusé"
        CHANGED = "changed", "événement modifié, reporté ou annulé"
        TO_MODERATE = "to_moderate", "événement à modérer (équipe)"
        ALERT = "alert", "nouvel événement pour une alerte"

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE, related_name="+")
    verb = models.CharField(max_length=20, choices=Verb.choices)
    event = models.ForeignKey("events.Event", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    message = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]


class Report(models.Model):
    """Signalement d'un événement ou d'un profil, traité par l'équipe dans /gestion/signalements/."""

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    event = models.ForeignKey("events.Event", null=True, blank=True, on_delete=models.CASCADE, related_name="reports")
    profile = models.ForeignKey(Profile, null=True, blank=True, on_delete=models.CASCADE, related_name="reports")
    comment = models.ForeignKey("Comment", null=True, blank=True, on_delete=models.CASCADE, related_name="reports")
    media = models.ForeignKey("Media", null=True, blank=True, on_delete=models.CASCADE, related_name="reports")
    reason = models.TextField("motif")
    created_at = models.DateTimeField(auto_now_add=True)
    handled = models.BooleanField("traité", default=False)

    class Meta:
        ordering = ["handled", "-created_at"]
        verbose_name = "signalement"

    @property
    def target(self):
        return self.comment or self.media or self.event or self.profile


class Comment(models.Model):
    """Commentaire d'un membre sur un événement, avec une note sur 5 une fois l'événement commencé."""

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments")
    body = models.TextField(_("commentaire"), max_length=2000, blank=True)
    # Une seule note comptée par membre et par événement : la plus récente (les anciennes sont remises à vide).
    rating = models.PositiveSmallIntegerField(_("note"), null=True, blank=True)
    is_hidden = models.BooleanField("masqué", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "commentaire"

    def __str__(self):
        text = self.body if len(self.body) <= 60 else self.body[:59] + "…"
        return text or f"{self.rating}/5"

    def get_absolute_url(self):
        return f"{self.event.get_absolute_url()}#commentaire-{self.pk}"


class Media(models.Model):
    """Photo, vidéo ou lien vers un média hébergé ailleurs (YouTube, Google Photos…), partagé sur un événement."""

    class Kind(models.TextChoices):
        PHOTO = "photo", _("Photo")
        VIDEO = "video", _("Vidéo")
        LINK = "lien", _("Lien")

    event = models.ForeignKey("events.Event", on_delete=models.CASCADE, related_name="media")
    uploader = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="media")
    kind = models.CharField(max_length=5, choices=Kind.choices)
    image = models.ImageField(upload_to="souvenirs/%Y/", blank=True)
    video = models.FileField(upload_to="souvenirs/%Y/", blank=True)
    url = models.URLField(max_length=500, blank=True)
    caption = models.CharField(_("légende"), max_length=200, blank=True)
    is_hidden = models.BooleanField("masqué", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "photo ou vidéo"
        verbose_name_plural = "photos et vidéos"

    def __str__(self):
        return self.caption or self.url or (self.image or self.video).name.rsplit("/", 1)[-1]

    def save(self, *args, **kwargs):
        normalize_field(self, "image")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        for field in (self.image, self.video):
            if field:
                field.delete(save=False)
        return super().delete(*args, **kwargs)

    def get_absolute_url(self):
        return f"{self.event.get_absolute_url()}#media-{self.pk}"

    @property
    def embed(self):
        from core.embeds import parse

        return parse(self.url) if self.url else None


class GoogleAccount(models.Model):
    """Compte Google relié (identifiant « sub », stable même si l'adresse Gmail change)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="google_accounts")
    sub = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "compte Google"
