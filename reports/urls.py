from django.urls import path
from django.views.generic import TemplateView
from . import views

urlpatterns = [
    path("", views.home_view, name="home"),
    path("about/", views.AboutView.as_view(), name="about"),
    path("stories/", views.stories_view, name="stories"),
    path("templates/", views.templates_view, name="templates"),
    path(
        "templates/<int:pk>/", views.storytemplate_detail_view, name="template_detail"
    ),
    path("stories/<int:story_id>/rate/", views.rate_story, name="rate_story"),
]
