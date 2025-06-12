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

User = get_user_model()


def login_view(request):
    if request.method == "POST":
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            login(request, form.get_user())
            return redirect("home")  # Adjust as needed
    else:
        form = AuthenticationForm()
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
            confirmation_link = reverse("account:confirm_email", args=[uid, token])
            activate_url = f"http://{domain}{confirmation_link}"

            subject = "Confirm your email"
            message = render_to_string(
                "account/email_confirmation.txt",
                {
                    "user": user,
                    "activate_url": activate_url,
                },
            )

            send_mail(subject, message, "noreply@yourdomain.com", [user.email])
            return redirect("account:email_sent")

    else:
        form = RegistrationForm()
    return render(request, "account/register.html", {"form": form})


def confirm_email(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        user = None

    if user and default_token_generator.check_token(user, token):
        user.is_active = True
        user.save()
        return render(request, "account/email_confirmed.html")
    else:
        return render(request, "account/email_invalid.html")


def profile_view(request):
    return render(request, "account/profile.html")


from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .forms import SubscriptionForm
from reports.models import StoryTemplateSubscription


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

            return redirect("account:profile")  # <– wichtig: Namespace!
    else:
        current_subscriptions = StoryTemplateSubscription.objects.filter(
            user=user, cancellation_date__isnull=True
        ).values_list("story_template_id", flat=True)

        form = SubscriptionForm(initial={"subscriptions": current_subscriptions})

    return render(request, "account/profile.html", {"form": form})
