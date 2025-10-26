# account/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models

# account/models.py

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.auth.base_user import BaseUserManager
from django.db import models
from django_countries.fields import CountryField


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")
        # ensure active by default when creating users
        extra_fields.setdefault("is_active", True)
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        # Ensure required superuser flags
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_staff") is not True or extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_staff=True and is_superuser=True.")
        return self.create_user(email, password, **extra_fields)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=30)
    last_name = models.CharField(max_length=30)
    country = CountryField(blank_label="(select country)")
    is_confirmed = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)
    last_active = models.DateTimeField(auto_now=True)
    auto_subscribe = models.BooleanField(default=False, help_text="Automatically subscribe to new insights and updates. This only applies to new content, it will not retroactively subscribe you to subscriptions you have cancelled.")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # ✅ required for admin access
    
    USERNAME_FIELD = "email"
    # Do NOT include 'password' here; Django handles password separately
    REQUIRED_FIELDS = ["first_name", "last_name", "country"]

    objects = CustomUserManager()

    def __str__(self):
        return self.email

    # Compatibility for code expecting .username attribute
    @property
    def username(self):
        return getattr(self, self.USERNAME_FIELD)

    @username.setter
    def username(self, value):
        """Allow assigning to `.username` by writing to the actual USERNAME_FIELD (email)."""
        setattr(self, self.USERNAME_FIELD, value)

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    def get_short_name(self):
        return self.first_name or self.email
