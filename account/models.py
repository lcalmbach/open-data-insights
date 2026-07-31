# account/models.py
from __future__ import annotations
import uuid
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.auth.base_user import BaseUserManager
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django_countries.fields import CountryField

DEFAULT_PREFERRED_LANGUAGE_ID = int(getattr(settings, "DEFAULT_PREFERRED_LANGUAGE_ID", 94))


def default_press_review_threshold():
    """Seed new users from the site-wide default so there is one source of truth."""
    return int(getattr(settings, "PRESSREVIEW_RELEVANCE_THRESHOLD", 7))


class NaturalKeyManager(models.Manager):
    """Generic manager supporting natural keys via lookup_fields."""
    lookup_fields: tuple[str, ...] = ()

    def get_by_natural_key(self, *args):
        return self.get(**dict(zip(self.lookup_fields, args)))


class Organisation(models.Model):
    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(unique=True, blank=True, null=True, editable=False)
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Organisation"
        verbose_name_plural = "Organisations"
        ordering = ("name",)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = uuid.uuid4().hex[:10]
        super().save(*args, **kwargs)


class CustomUserManager(BaseUserManager, NaturalKeyManager):
    lookup_fields = ("slug",)
    use_in_migrations = True

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")

        email = self.normalize_email(email)
        extra_fields.setdefault("is_active", True)

        user = self.model(email=email, **extra_fields)

        # ensure slug on first save
        if not getattr(user, "slug", None):
            user.slug = uuid.uuid4().hex[:10]

        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_staff") is not True or extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_staff=True and is_superuser=True.")
        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    slug = models.SlugField(unique=True, blank=True, null=True, editable=False)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=30)
    last_name  = models.CharField(max_length=30)
    country = CountryField(blank_label="(select country)")
    preferred_language = models.ForeignKey(
        "reports.Language",
        blank=True,
        null=True,
        default=DEFAULT_PREFERRED_LANGUAGE_ID,  # Default to English
        on_delete=models.SET_NULL,
        related_name="users",
        limit_choices_to={"category_id": 10},
        help_text="Preferred language for the UI/content, based on lookup values (category_id=10).",
    )
    organisation = models.ForeignKey(
        "account.Organisation",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="members",
        help_text="Assign this user to an organisation to unlock organisation-specific insights.",
    )
    is_confirmed = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)
    last_active = models.DateTimeField(auto_now=True)
    auto_subscribe = models.BooleanField(
        default=False,
        help_text=(
            "Automatically subscribe to new insights and updates. "
            "This only applies to new content; it will not retroactively "
            "re-subscribe cancelled subscriptions."
        ),
    )
    PRESS_REVIEW_FREQUENCY_NONE = "none"
    PRESS_REVIEW_FREQUENCY_DAILY = "daily"
    PRESS_REVIEW_FREQUENCY_WEEKLY = "weekly"
    PRESS_REVIEW_FREQUENCY_CHOICES = (
        (PRESS_REVIEW_FREQUENCY_NONE, "No press review digest"),
        (PRESS_REVIEW_FREQUENCY_DAILY, "Daily digest"),
        (PRESS_REVIEW_FREQUENCY_WEEKLY, "Weekly digest"),
    )

    press_review_threshold = models.PositiveSmallIntegerField(
        default=default_press_review_threshold,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text=(
            "Minimum AI relevance score (1-10) an article must reach to appear in "
            "this user's digest. Lower it to widen the net, raise it to cut noise. "
            "Scores are stored for every article, so lowering it also surfaces "
            "previously scored articles at no extra cost."
        ),
    )
    press_review_frequency = models.CharField(
        max_length=16,
        choices=PRESS_REVIEW_FREQUENCY_CHOICES,
        default=PRESS_REVIEW_FREQUENCY_DAILY,
        help_text=(
            "How often to send this user's press review digest. "
            "Mutually exclusive so an article is never sent twice."
        ),
    )
    press_review_sources = models.ManyToManyField(
        "reports.PressReviewSource",
        blank=True,
        related_name="subscribed_users",
        help_text=(
            "RSS sources to include in this user's press review digest. "
            "Leave empty to include all active sources."
        ),
    )
    is_active = models.BooleanField(default=True)
    is_staff  = models.BooleanField(default=False)  # required for admin access

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name", "country"]

    objects = CustomUserManager()
    all_objects = models.Manager()  # optional plain manager

    def __str__(self):
        return self.email

    @property
    def username(self):
        return getattr(self, self.USERNAME_FIELD)

    @username.setter
    def username(self, value):
        setattr(self, self.USERNAME_FIELD, value)

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name or self.email

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = uuid.uuid4().hex[:10]
        super().save(*args, **kwargs)

    # Natural key (useful for fixtures/sync by slug)
    def natural_key(self):
        return (self.slug,)
    natural_key.dependencies = []
