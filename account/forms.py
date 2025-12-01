from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.utils.safestring import mark_safe
from account.models import CustomUser
from django_countries.widgets import CountrySelectWidget

from reports.models.story_template import StoryTemplate


class CustomUserUpdateForm(forms.ModelForm):
    # E-Mail nur anzeigen (nicht änderbar)
    email = forms.EmailField(disabled=True, required=False, label="Email")

    class Meta:
        model = CustomUser
        fields = ["first_name", "last_name", "country", "auto_subscribe", "email"]  # email nicht speichern
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "country": CountrySelectWidget(attrs={"class": "form-select"}),
            "auto_subscribe": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "first_name": "First name",
            "last_name": "Last name",
            "country": "Country",
            "auto_subscribe": "Auto subscribe to new content",
        }

class RegistrationForm(UserCreationForm):
    class Meta:
        model = get_user_model()
        fields = ("email", "first_name", "last_name", "country", "auto_subscribe")
        labels = {
            "auto_subscribe": "Auto subscribe to new content",
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_active = True    # ensure active on registration
        if commit:
            user.save()
        return user

class SubscriptionForm(forms.Form):
    subscriptions = forms.ModelMultipleChoiceField(
        queryset=StoryTemplate.objects.filter(active=True),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Your subscriptions",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["subscriptions"].label_from_instance = self.custom_label

    def custom_label(self, obj):
        url = f"/templates/{obj.pk}/"
        return mark_safe(f'{obj.title} ({obj.reference_period}) – <a href="{url}" target="_blank">Details</a>')

    @property
    def toggle_control(self):
        """HTML button to toggle all subscription checkboxes (render in the template)."""
        return mark_safe(
            '<button type="button" id="toggle-subscriptions" class="btn btn-outline-secondary mb-2">Toggle all</button>'
        )

    @property
    def toggle_script(self):
        """Inline JS to wire the toggle button. Render once (e.g. right after the form)."""
        return mark_safe(
            """
<script>
document.addEventListener('DOMContentLoaded', function () {
  const btn = document.getElementById('toggle-subscriptions');
  if (!btn) return;
  btn.addEventListener('click', function () {
    // select inputs with the form field name; CheckboxSelectMultiple uses name="subscriptions"
    const boxes = Array.from(document.querySelectorAll('input[name="subscriptions"]'));
    if (!boxes.length) return;
    const allChecked = boxes.every(b => b.checked);
    boxes.forEach(b => b.checked = !allChecked);
  });
});
</script>
            """
        )
