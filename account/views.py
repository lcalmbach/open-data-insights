from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib.sites.shortcuts import get_current_site
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.template.loader import render_to_string
from django.contrib.auth.tokens import default_token_generator
from .forms import RegistrationForm
from .forms import SubscriptionForm
from reports.models import StoryTemplateSubscription, StoryTemplate
from django.utils import timezone
from django.contrib.auth import authenticate, login
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import BaseUserManager
from django.core.exceptions import MultipleObjectsReturned
import logging

logger = logging.getLogger(__name__)

User = get_user_model()


def login_view(request):
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            # AuthenticationForm already authenticated the user
            user = form.get_user()
            login(request, user)
            return redirect("home")

        # keep a concise debug log for failed attempts
        logger.warning(
            "Login form invalid. errors=%s non_field_errors=%s cleaned_data=%s",
            form.errors.as_json(),
            form.non_field_errors(),
            form.cleaned_data,
        )
        messages.error(
            request,
            "Please enter a correct email and password. Note that both fields may be case-sensitive.",
        )
    else:
        form = AuthenticationForm(request)

    return render(request, "account/login.html", {"form": form})


@login_required
def logout_view(request):
    logout(request)
    return redirect("home")


def register_view(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Account created successfully. Please log in.")
            return redirect("login")
    else:
        form = RegistrationForm()
    return render(request, "account/register.html", {"form": form})


def register(request):
    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_active = False  # Wait for confirmation
            user.username = form.cleaned_data["email"]  # optional, if username required
            user.save()

            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            domain = get_current_site(request).domain
            confirmation_link = reverse("account:confirm_email", kwargs={"uidb64": uid, "token": token})
            activate_url = f"http://{domain}{confirmation_link}"
            subject = "Confirm your email"
            message = render_to_string(
                "account/email_confirmation.txt",
                {
                    "user": user,
                    "activate_url": activate_url,
                },
            )

            send_mail(subject, message, "lcalmbach@gmail.com", [user.email])
            messages.success(request, "Account created! Please check your email to confirm your address.")
            return redirect("home")

    else:
        form = RegistrationForm()
    return render(request, "account/register.html", {"form": form})


def confirm_email(request, uidb64, token):
    try:
        uid = urlsafe_base64_decode(uidb64).decode()
        user = get_user_model().objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, get_user_model().DoesNotExist):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        if not user.is_active:
            user.is_active = True
            user.save()
            messages.success(request, "Deine E-Mail-Adresse wurde bestätigt. Du kannst dich jetzt einloggen.")
        else:
            messages.info(request, "Deine E-Mail-Adresse war bereits bestätigt.")
        return redirect("login")  # oder dein home-View
    else:
        messages.error(request, "Dieser Bestätigungslink ist ungültig oder abgelaufen.")
        return render(request, "account/email_confirmation_invalid.html")



@login_required
def profile_view(request):
    user = request.user

    if request.method == "POST":
        form = SubscriptionForm(request.POST)
        if form.is_valid():
            selected_templates = form.cleaned_data["subscriptions"]

            # Bestehende Subscriptions beenden
            StoryTemplateSubscription.objects.filter(
                user=user, cancellation_date__isnull=True
            ).exclude(story_template__in=selected_templates).update(
                cancellation_date=timezone.now()
            )

            # Neue hinzufügen
            for template in selected_templates:
                StoryTemplateSubscription.objects.get_or_create(
                    user=user,
                    story_template=template,
                    cancellation_date__isnull=True,
                    defaults={"user": user, "story_template": template},
                )
            messages.success(request, "Your subscriptions have been saved.")
            return redirect("account:profile")  # <– wichtig: Namespace!
    else:
        current_subscriptions = StoryTemplateSubscription.objects.filter(
            user=user, cancellation_date__isnull=True
        ).values_list("story_template_id", flat=True)

        form = SubscriptionForm(initial={"subscriptions": current_subscriptions})

    return render(request, "account/profile.html", {"form": form})
