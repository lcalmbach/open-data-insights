from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit


class StoryRatingForm(forms.Form):
    rating = forms.IntegerField(min_value=1, max_value=5, label="Sterne")
    rating_text = forms.CharField(widget=forms.Textarea, required=False, label="Dein Feedback")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = "post"
        self.helper.add_input(Submit("submit", "Bewertung absenden"))