from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils.safestring import mark_safe
from .models import CustomUser
from reports.models import StoryTemplate


class RegistrationForm(UserCreationForm):
    class Meta:
        model = CustomUser
        fields = ("email", "first_name", "last_name", "country")


class SubscriptionForm(forms.Form):
    subscriptions = forms.ModelMultipleChoiceField(
        queryset=StoryTemplate.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Your subscriptions",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subscriptions"].label_from_instance = self.custom_label

    def custom_label(self, obj):
        url = f"/templates/{obj.pk}/"
        return mark_safe(f'{obj.title} – <a href="{url}" target="_blank">Details</a>')
