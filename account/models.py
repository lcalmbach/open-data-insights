# account/models.py
from __future__ import annotations
import uuid
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.auth.base_user import BaseUserManager
from django.db import models
from django_countries.fields import CountryField


class NaturalKeyManager(models.Manager):
    """Generic manager supporting natural keys via lookup_fields."""
    lookup_fields: tuple[str, ...] = ()

    def get_by_natural_key(self, *args):
        return self.get(**dict(zip(self.lookup_fields, args)))


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
