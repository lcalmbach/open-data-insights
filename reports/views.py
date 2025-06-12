from django.shortcuts import render
from django.http import HttpResponse
from .models import StoryTemplate, Story
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.shortcuts import render, get_object_or_404
from account.forms import SubscriptionForm
import markdown2

@never_cache
def home_view(request):
    story = Story.objects.order_by("-published_date").first()  # oder beliebige Logik
    story.content_html = markdown2.markdown(story.content, extras=["tables"])
    print(story.content_html )
    return render(request, "home.html", {"story": story})


def templates_view(request):
    templates = StoryTemplate.objects.all()
    selected_template_id = request.GET.get("template")
    selected_template = None

    if selected_template_id:
        selected_template = get_object_or_404(StoryTemplate, id=selected_template_id)

    return render(
        request,
        "reports/templates_list.html",
        {
            "templates": templates,
            "selected_template": selected_template,
        },
    )


def stories_view(request):
    stories = Story.objects.order_by("-published_date")
    selected_story_id = request.GET.get("story")
    selected_story = None

    if selected_story_id:
        selected_story = get_object_or_404(Story, id=selected_story_id)

    return render(
        request,
        "reports/stories_list.html",
        {
            "stories": stories,
            "selected_story": selected_story,
        },
    )


def storytemplate_detail_view(request, pk):
    template = get_object_or_404(StoryTemplate, pk=pk)
    back_url = request.META.get("HTTP_REFERER", "/")  # fallback: Startseite
    return render(
        request,
        "reports/storytemplate_detail.html",
        {
            "template": template,
            "back_url": back_url,
        },
    )
