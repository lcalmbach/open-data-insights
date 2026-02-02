from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit


class StoryRatingForm(forms.Form):
    rating = forms.IntegerField(min_value=1, max_value=5, label="Sterne")
    rating_text = forms.CharField(
        widget=forms.Textarea, required=False, label="Your Feedback (optional)"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", "Bewertung absenden"))


class UserCommentForm(forms.Form):
    comment = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 6}),
        label="Your message",
        help_text="Share feedback, ideas, bug reports, or suggestions.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", "Send"))
