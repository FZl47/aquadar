from django.apps import apps as django_apps
from django.conf import settings

from .claude import ClaudeProvider
from .base import ProviderError
from .gemini import GeminiProvider
from .openai_compatible import ChatGPTProvider, DeepSeekProvider, GapGPTProvider, GrokProvider

PROVIDER_CLASSES = {
    provider.name: provider
    for provider in (
        ChatGPTProvider,
        GapGPTProvider,
        GrokProvider,
        ClaudeProvider,
        GeminiProvider,
        DeepSeekProvider,
    )
}

PROVIDER_TYPE_CHOICES = tuple((name, provider.label) for name, provider in PROVIDER_CLASSES.items())
BUILTIN_PROVIDER_NAMES = tuple(PROVIDER_CLASSES)


def get_ai_config():
    return getattr(settings, 'AI_ASSISTANT_CONFIG', {})


def get_active_configs():
    config_model = django_apps.get_model('ai_assistant', 'AIProviderConfig')
    return {row.key: row for row in config_model.objects.filter(is_active=True)}


def _build_provider(name, row=None):
    type_name = row.provider_type if row else name
    provider_class = PROVIDER_CLASSES.get(type_name)
    if provider_class is None:
        raise ProviderError(f'ارائه‌دهنده «{name}» پشتیبانی نمی‌شود')
    config = get_ai_config()
    provider_config = dict(config.get('PROVIDERS', {}).get(name, {}))
    provider_config.setdefault('TIMEOUT', config.get('TIMEOUT', 120))
    if row:
        provider_config.update({
            key: value for key, value in (
                ('API_KEY', row.api_key), ('MODEL', row.model), ('BASE_URL', row.base_url),
            ) if value
        })
    provider = provider_class(provider_config)
    provider.name = name
    provider.label = row.label if row else provider_class.label
    provider.config_row = row
    provider.is_custom = name not in BUILTIN_PROVIDER_NAMES
    return provider


def get_provider(name):
    return _build_provider(name, get_active_configs().get(name))


def provider_names(rows):
    custom = [name for name in rows if name not in BUILTIN_PROVIDER_NAMES]
    return list(BUILTIN_PROVIDER_NAMES) + custom


def list_providers():
    rows = get_active_configs()
    return [_build_provider(name, rows.get(name)) for name in provider_names(rows)]


def get_provider_labels():
    return {provider.name: provider.label for provider in list_providers()}


def provider_choices():
    return tuple((provider.name, provider.label) for provider in list_providers())


def get_default_provider_name():
    return get_ai_config().get('DEFAULT_PROVIDER', 'gemini')
