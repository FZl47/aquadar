from django import forms

from . import models

class NotificationUserCreateForm(forms.ModelForm):

    class Meta:
        model = models.NotificationUser
        exclude = ('type',)
