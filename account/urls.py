from django.urls import path
from django.contrib.auth import views as auth_views
from django.shortcuts import render
from . import views

app_name = 'account'
urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("register/", views.register, name="register"),  # keep only one
    path("set-language/", views.set_language, name="set_language"),
    path("confirm/<uidb64>/<token>/", views.confirm_email, name="confirm_email"),
    path("email-sent/", lambda r: render(r, "account/email_sent.html"), name="email_sent"),

    # Password reset flow (via email)
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
        "confirm/<uidb64>/<token>/",
        views.confirm_email,
        name="confirm_email",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="account/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),


    path("profile/", views.profile_view, name="profile"),
    path("delete/", views.delete_account_view, name="delete_account"),
]
