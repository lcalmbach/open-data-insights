from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

app_name = "account"  # ← this enables the 'account:' prefix in {% url %}

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("register/", views.register_view, name="register"),
    path("register/", views.register, name="register"),
    path("confirm/<uidb64>/<token>/", views.confirm_email, name="confirm_email"),
    path(
        "email-sent/", lambda r: render(r, "account/email_sent.html"), name="email_sent"
    ),
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="account/password_reset.html"
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="account/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="account/password_reset_confirm.html"
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="account/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path("profile/", views.profile_view, name="profile"),
]
