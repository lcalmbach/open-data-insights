from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.utils.safestring import mark_safe
from account.models import CustomUser
from django_countries.widgets import CountrySelectWidget

from reports.models.story_template import StoryTemplate
from reports.models.press_review import PressReviewSource, UserPressReviewKeyword


class CustomUserUpdateForm(forms.ModelForm):
    # E-Mail nur anzeigen (nicht änderbar)
    email = forms.EmailField(disabled=True, required=False, label="Email")

    class Meta:
        model = CustomUser
        fields = [
            "first_name",
            "last_name",
            "country",
            "preferred_language",
            "auto_subscribe",
            "email",
        ]  # email nicht speichern
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "country": CountrySelectWidget(attrs={"class": "form-select"}),
            "preferred_language": forms.Select(attrs={"class": "form-select"}),
            "auto_subscribe": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "first_name": "First name",
            "last_name": "Last name",
            "country": "Country",
            "preferred_language": "Preferred language",
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

class PressReviewPreferencesForm(forms.Form):
    frequency = forms.ChoiceField(
        choices=CustomUser.PRESS_REVIEW_FREQUENCY_CHOICES,
        widget=forms.RadioSelect,
        label="Digest frequency",
        help_text="Daily and weekly are mutually exclusive, so you never get the same article twice.",
    )
    threshold = forms.IntegerField(
        min_value=1,
        max_value=10,
        label="Relevance threshold",
        help_text=(
            "Only articles the AI scores at or above this value (1-10) reach you. "
            "Lower it to widen the net, raise it to cut noise."
        ),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": 1}),
    )
    keywords = forms.CharField(
        required=False,
        label="Press review topics",
        help_text="Comma-separated topics you're interested in, e.g. 'Basel, Wohnen, Klima'.",
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
    )
    sources = forms.ModelMultipleChoiceField(
        queryset=PressReviewSource.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="News sources",
        help_text="Leave all unchecked to include every available source.",
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        if user is not None and "initial" not in kwargs:
            kwargs["initial"] = {
                "frequency": user.press_review_frequency,
                "threshold": user.press_review_threshold,
                "keywords": ", ".join(user.press_review_keywords.values_list("keyword", flat=True)),
                "sources": user.press_review_sources.all(),
            }
        super().__init__(*args, **kwargs)
        self.fields["sources"].queryset = PressReviewSource.objects.filter(active=True)

    def save(self):
        submitted = {
            kw.strip() for kw in self.cleaned_data["keywords"].split(",") if kw.strip()
        }
        existing = set(
            self.user.press_review_keywords.values_list("keyword", flat=True)
        )
        UserPressReviewKeyword.objects.bulk_create(
            [
                UserPressReviewKeyword(user=self.user, keyword=kw)
                for kw in submitted - existing
            ]
        )
        self.user.press_review_keywords.filter(keyword__in=existing - submitted).delete()
        self.user.press_review_sources.set(self.cleaned_data["sources"])
        self.user.press_review_frequency = self.cleaned_data["frequency"]
        self.user.press_review_threshold = self.cleaned_data["threshold"]
        self.user.save(update_fields=["press_review_frequency", "press_review_threshold"])


class SubscriptionForm(forms.Form):
    subscriptions = forms.ModelMultipleChoiceField(
        queryset=StoryTemplate.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Your subscriptions",
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["subscriptions"].queryset = StoryTemplate.objects.accessible_to(user)
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
