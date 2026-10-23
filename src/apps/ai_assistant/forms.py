from django import forms

from apps.public.models import Experiment

from .models import AISettings
from .providers.registry import PROVIDER_CHOICES, get_provider


def _ensure_provider_configured(provider_name):
    provider = get_provider(provider_name)
    if not provider.is_configured:
        raise forms.ValidationError(f'کلید API برای {provider.label} در تنظیمات سرور وارد نشده است.')
    return provider_name


class ExperimentAnalyzeForm(forms.Form):
    experiment = forms.ModelChoiceField(
        queryset=Experiment.objects.order_by('-date', '-id'),
        label='آزمایش',
        empty_label='انتخاب آزمایش',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    provider = forms.ChoiceField(
        required=False,
        label='ارائه‌دهنده هوش مصنوعی',
        choices=(('', 'ارائه‌دهنده اصلی (طبق تنظیمات)'),) + PROVIDER_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, main_provider='', **kwargs):
        super().__init__(*args, **kwargs)
        self.main_provider = main_provider

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        provider_name = cleaned.get('provider') or self.main_provider
        try:
            cleaned['provider_name'] = _ensure_provider_configured(provider_name)
        except forms.ValidationError as exc:
            self.add_error('provider', exc)
        return cleaned


class AISettingsForm(forms.ModelForm):
    class Meta:
        model = AISettings
        fields = ['main_provider']
        widgets = {
            'main_provider': forms.Select(attrs={'class': 'form-control'}),
        }

    def clean_main_provider(self):
        provider_name = self.cleaned_data.get('main_provider')
        if provider_name:
            _ensure_provider_configured(provider_name)
        return provider_name
