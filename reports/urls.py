from django.urls import path
from django.views.generic import TemplateView
from . import views

urlpatterns = [
    path('', views.home_view, name='home'),
    path('about/', TemplateView.as_view(template_name='about.html'), name='about'),
    path('explore/', views.explore_view, name='explore'),
    path("templates/<int:pk>/", views.storytemplate_detail_view, name="template_detail"),
]