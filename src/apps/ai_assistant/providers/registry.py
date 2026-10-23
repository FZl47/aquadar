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

PROVIDER_CHOICES = tuple((name, provider.label) for name, provider in PROVIDER_CLASSES.items())


def get_ai_config():
    return getattr(settings, 'AI_ASSISTANT_CONFIG', {})


def get_provider(name):
    provider_class = PROVIDER_CLASSES.get(name)
    if provider_class is None:
        raise ProviderError(f'ارائه‌دهنده «{name}» پشتیبانی نمی‌شود')
    config = get_ai_config()
    provider_config = dict(config.get('PROVIDERS', {}).get(name, {}))
    provider_config.setdefault('TIMEOUT', config.get('TIMEOUT', 120))
    return provider_class(provider_config)


def get_default_provider_name():
    return get_ai_config().get('DEFAULT_PROVIDER', 'gemini')


def list_providers():
    return [get_provider(name) for name in PROVIDER_CLASSES]
