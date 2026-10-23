from django import forms

from . import models

class NotificationUserCreateForm(forms.ModelForm):

    class Meta:
        model = models.NotificationUser
        exclude = ('type',)


class NotificationConfigForm(forms.ModelForm):

    class Meta:
        model = models.NotificationConfig
        fields = ['send_sms_notify', 'send_email_notify', 'send_rubika_notify']
        widgets = {
            'send_sms_notify': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'send_email_notify': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'send_rubika_notify': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
