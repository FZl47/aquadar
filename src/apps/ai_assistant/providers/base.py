from dataclasses import dataclass

import requests

KIND_IMAGE = 'image'
KIND_PDF = 'pdf'
KIND_TEXT = 'text'
KIND_UNSUPPORTED = 'unsupported'


class ProviderError(Exception):
    pass


@dataclass
class Attachment:
    label: str
    filename: str
    kind: str
    mime_type: str = ''
    data: bytes = b''
    text: str = ''


class BaseProvider:
    name = ''
    label = ''
    supports_images = False
    supports_pdf = False
    default_model = ''
    default_base_url = ''

    def __init__(self, config):
        self.api_key = config.get('API_KEY') or ''
        self.model = config.get('MODEL') or self.default_model
        self.base_url = (config.get('BASE_URL') or self.default_base_url).rstrip('/')
        self.timeout = config.get('TIMEOUT') or 120

    @property
    def is_configured(self):
        return bool(self.api_key)

    def generate(self, system_prompt, user_prompt, attachments):
        raise NotImplementedError

    def attachment_as_text(self, attachment):
        header = f'### {attachment.label} ({attachment.filename})'
        if attachment.text:
            return f'{header}\n{attachment.text}'
        if attachment.kind == KIND_IMAGE:
            return f'{header}\n[این ارائه‌دهنده امکان خواندن تصویر ندارد؛ محتوای فایل در دسترس نیست.]'
        if attachment.kind == KIND_PDF:
            return f'{header}\n[متن قابل استخراج از این PDF وجود ندارد؛ محتوای فایل در دسترس نیست.]'
        return f'{header}\n[فرمت این فایل قابل خواندن نیست؛ محتوای فایل در دسترس نیست.]'

    def is_native_attachment(self, attachment):
        if attachment.kind == KIND_IMAGE:
            return self.supports_images
        if attachment.kind == KIND_PDF:
            return self.supports_pdf
        return False

    def post_json(self, url, headers, payload):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ProviderError(f'{self.label}: خطا در برقراری ارتباط ({exc})') from exc
        if response.status_code >= 400:
            raise ProviderError(f'{self.label}: HTTP {response.status_code} - {response.text[:500]}')
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError(f'{self.label}: پاسخ نامعتبر از سرویس') from exc
