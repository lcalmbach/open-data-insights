from django.urls import path
from django.views.generic import TemplateView
from . import views

urlpatterns = [
    path("", views.home_view, name="home"),
    path("about/", views.AboutView.as_view(), name="about"),
    path("story/<int:story_id>/", views.view_story, name="view_story"),
    path("story_detail/<int:story_id>/", views.story_detail, name="story_detail"),
    path(
        "story_detail/<int:story_id>/delete/",
        views.delete_story,
        name="delete_story",
    ),
    path("stories/", views.stories_view, name="stories"),
    path("datasets/", views.datasets_view, name="datasets"),
    path("templates/", views.templates_view, name="templates"),
    path(
        "templates/<int:pk>/", views.storytemplate_detail_view, name="template_detail"
    ),
    path("stories/<int:story_id>/rate/", views.rate_story, name="rate_story"),
    path("feedback/", views.user_feedback_view, name="user_feedback"),
    path(
        "tables/<int:table_id>/download/",
        views.download_story_table_csv,
        name="story_table_download",
    ),
    path("management/commands/", views.run_commands_view, name="run_commands"),
    path("management/query/", views.query_datasets_view, name="query_datasets"),
    path("management/email/", views.email_users_view, name="email_users"),
]
