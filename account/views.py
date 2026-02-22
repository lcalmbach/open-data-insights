from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.base_user import BaseUserManager
from django.shortcuts import render, redirect
from django.contrib.sites.shortcuts import get_current_site
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.utils import timezone
from django.template.loader import render_to_string
from django.contrib.auth.tokens import default_token_generator
from .forms import RegistrationForm
from .forms import SubscriptionForm
from .forms import CustomUserUpdateForm
from django.core.exceptions import MultipleObjectsReturned
from django.conf import settings
from django.db import transaction
from django.views.decorators.http import require_POST
import logging

from reports.models.subscription import StoryTemplateSubscription
from reports.models.story_template import StoryTemplate
from reports.language import get_content_language_id, set_content_language_id

logger = logging.getLogger(__name__)

User = get_user_model()


@login_required
def profile_view(request):
    user = request.user
    current_subscriptions = StoryTemplateSubscription.objects.filter(
            user=user, cancellation_date__isnull=True, story_template__active=True
        ).values_list("story_template_id", flat=True)
    if request.method == "POST":
        action = request.POST.get("action")

        # --- Profil speichern ---
        if action == "save_profile":
            profile_form = CustomUserUpdateForm(request.POST, instance=user)

            # Für den unteren Bereich nur "anzeigefähig" initialisieren
            current_subscriptions = StoryTemplateSubscription.objects.filter(
                user=user, cancellation_date__isnull=True, story_template__active=True
            ).values_list("story_template_id", flat=True)
            subscriptions_form = SubscriptionForm(initial={"subscriptions": current_subscriptions}, user=user)

            if profile_form.is_valid():
                profile_form.save()
                if getattr(user, "preferred_language_id", None):
                    set_content_language_id(request, user.preferred_language_id)
                messages.success(request, "Your profile has been updated.")
                return redirect("account:profile")

        # --- Subscriptions speichern ---
        elif action == "save_subscriptions":
            profile_form = CustomUserUpdateForm(instance=user)

            subscriptions_form = SubscriptionForm(request.POST, user=user)
            if subscriptions_form.is_valid():
                selected_templates = subscriptions_form.cleaned_data["subscriptions"]

                # Änderungen atomar durchführen
                with transaction.atomic():
                    # Bestehende Subscriptions beenden, die nicht mehr ausgewählt sind
                    StoryTemplateSubscription.objects.filter(
                        user=user, cancellation_date__isnull=True, story_template__active=True
                    ).exclude(
                        story_template__in=selected_templates
                    ).update(
                        cancellation_date=timezone.now()
                    )

                    # Neue hinzufügen (oder bestehende fortschreiben)
                    for template in selected_templates:
                        # Alle aktiven Subscriptions für user+template holen
                        active_qs = StoryTemplateSubscription.objects.filter(
                            user=user,
                            story_template=template,
                            cancellation_date__isnull=True,
                        )

                        if active_qs.exists():
                            # Falls es mehrere sind, optional aufräumen: nur eine aktiv lassen
                            main = active_qs.first()
                            # Die anderen ggf. mit cancellation_date setzen (oder löschen)
                            active_qs.exclude(pk=main.pk).update(cancellation_date=timezone.now())
                            # Nichts neues anlegen – es existiert ja schon eine aktive
                        else:
                            # Neue aktive Subscription anlegen
                            StoryTemplateSubscription.objects.create(
                                user=user,
                                story_template=template,
                            )

                messages.success(request, "Your subscriptions have been saved.")
                return redirect("account:profile")

        else:
            # Fallback: beide Formulare binden, damit Fehler sichtbar sind
            profile_form = CustomUserUpdateForm(request.POST, instance=user)
            subscriptions_form = SubscriptionForm(request.POST, user=user)

    else:
        # GET: beide Formulare befüllen
        profile_form = CustomUserUpdateForm(instance=user)
        subscriptions_form = SubscriptionForm(initial={"subscriptions": current_subscriptions}, user=user)

    return render(
        request,
        "account/profile.html",
        {
            "profile_form": profile_form,    # oben im Template verwenden
            "form": subscriptions_form,      # dein bestehender Name unten
            "active_subscriptions": current_subscriptions.count()
        },
    )


def login_view(request):
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            # AuthenticationForm already authenticated the user
            user = form.get_user()
            login(request, user)
            if getattr(user, "preferred_language_id", None):
                set_content_language_id(request, user.preferred_language_id)
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


@require_POST
def set_language(request):
    next_url = (request.POST.get("next") or "").strip() or request.META.get(
        "HTTP_REFERER", "/"
    )
    raw_id = (request.POST.get("language_id") or "").strip()
    try:
        language_id = int(raw_id)
    except (TypeError, ValueError):
        messages.error(request, "Invalid language selection.")
        return redirect(next_url)

    from reports.models.lookups import Language

    if not Language.objects.filter(id=language_id).exists():
        messages.error(request, "Unknown language selection.")
        return redirect(next_url)

    set_content_language_id(request, language_id)

    if getattr(request.user, "is_authenticated", False):
        if getattr(request.user, "preferred_language_id", None) != language_id:
            request.user.preferred_language_id = language_id
            request.user.save(update_fields=["preferred_language"])

    return redirect(next_url)


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
        if not user.is_confirmed:
            user.is_confirmed = True
            user.save()

            # Send welcome email with list of available templates to subscribe to
            try:
                domain = get_current_site(request).domain
                protocol = "https" if request.is_secure() else "http"
                templates = StoryTemplate.objects.accessible_to(user)
                if templates.exists():
                    # build absolute profile URL at runtime (no hardcoded host)
                    profile_url = request.build_absolute_uri(reverse("account:profile"))
                    lines = [
                        f"Hello {user.get_full_name() or user.email},",
                        "",
                        "Welcome and congratulations! Your email has been confirmed.",
                        "",
                        "Would you like me to take you to your profile so you can subscribe to some of the following insights and be notified when they are published?",
                        "",
                        "You can manage your subscriptions here:",
                        profile_url,
                        "",
                        "The following insights are available for subscription:",
                        "",
                    ]
                    root = f"{protocol}://{domain}".rstrip("/")
                    for t in templates:
                        lines.append(f"- {t.title}: {root}/templates/?template={t.id}")

                    subject = "Welcome to Open Data Insights"
                    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", f"no-reply@{domain}")
                    send_mail(subject, "\n".join(lines), from_email, [user.email])
            except Exception as e:
                logger.exception("Failed to send welcome email to user %s: %s", user.pk, e)

            messages.success(request, "Deine E-Mail-Adresse wurde bestätigt. Du kannst dich jetzt einloggen.")
            
        else:
            messages.info(request, "Deine E-Mail-Adresse war bereits bestätigt.")
        return redirect("login")  # oder dein home-View
    else:
        messages.error(request, "Dieser Bestätigungslink ist ungültig oder abgelaufen.")
        return render(request, "account/email_confirmation_invalid.html")


@login_required
def delete_account_view(request):
    """Ask for confirmation, then delete the logged-in user."""
    if request.method == "POST":
        user_email = request.user.email
        request.user.delete()
        messages.success(request, f"Account {user_email} has been deleted.")
        return redirect("home")  # or your landing page

    return render(request, "account/delete_account_confirm.html")
