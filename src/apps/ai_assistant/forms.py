from django import forms

from apps.public.models import Experiment

from .models import AIProviderConfig, AISettings
from .providers.registry import BUILTIN_PROVIDER_NAMES, get_provider, provider_choices


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
        choices=(),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, main_provider='', **kwargs):
        super().__init__(*args, **kwargs)
        self.main_provider = main_provider
        self.fields['provider'].choices = (('', 'ارائه‌دهنده اصلی (طبق تنظیمات)'),) + provider_choices()

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
    main_provider = forms.ChoiceField(
        required=False,
        label='ارائه‌دهنده اصلی',
        choices=(),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    class Meta:
        model = AISettings
        fields = ['main_provider']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['main_provider'].choices = (('', 'پیش‌فرض فایل تنظیمات سرور'),) + provider_choices()

    def clean_main_provider(self):
        provider_name = self.cleaned_data.get('main_provider')
        if provider_name:
            _ensure_provider_configured(provider_name)
        return provider_name


class AIProviderConfigForm(forms.ModelForm):
    api_key = forms.CharField(
        required=False,
        label='کلید API',
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'dir': 'ltr', 'autocomplete': 'new-password'}),
        help_text='برای حفظ کلید فعلی، این فیلد را خالی بگذارید',
    )

    class Meta:
        model = AIProviderConfig
        fields = ['key', 'label', 'provider_type', 'api_key', 'model', 'base_url', 'is_active']
        widgets = {
            'key': forms.TextInput(attrs={'class': 'form-control', 'dir': 'ltr', 'placeholder': 'my-provider'}),
            'label': forms.TextInput(attrs={'class': 'form-control'}),
            'provider_type': forms.Select(attrs={'class': 'form-control'}),
            'model': forms.TextInput(attrs={'class': 'form-control', 'dir': 'ltr'}),
            'base_url': forms.URLInput(attrs={'class': 'form-control', 'dir': 'ltr'}),
            'is_active': forms.CheckboxInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['key'].disabled = True
            self.fields['provider_type'].disabled = True

    def clean_key(self):
        return (self.cleaned_data.get('key') or '').lower()

    def clean(self):
        cleaned = super().clean()
        key = cleaned.get('key')
        provider_type = cleaned.get('provider_type')
        if key in BUILTIN_PROVIDER_NAMES and provider_type and provider_type != key:
            self.add_error('provider_type', f'برای شناسه «{key}» باید نوع سرویس همان مقدار باشد.')
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not self.cleaned_data.get('api_key') and self.instance.pk:
            instance.api_key = AIProviderConfig.objects.values_list('api_key', flat=True).get(pk=instance.pk)
        if commit:
            instance.save()
        return instance
