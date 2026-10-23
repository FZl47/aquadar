import base64

from .base import KIND_IMAGE, BaseProvider, ProviderError


class ClaudeProvider(BaseProvider):
    name = 'claude'
    label = 'Claude (Anthropic)'
    supports_images = True
    supports_pdf = True
    default_model = 'claude-sonnet-4-6'
    default_base_url = 'https://api.anthropic.com/v1'
    api_version = '2023-06-01'
    max_tokens = 8192

    def generate(self, system_prompt, user_prompt, attachments):
        content = [{'type': 'text', 'text': user_prompt}]
        for attachment in attachments:
            if self.is_native_attachment(attachment):
                content.append({'type': 'text', 'text': f'### {attachment.label} ({attachment.filename})'})
                content.append({
                    'type': 'image' if attachment.kind == KIND_IMAGE else 'document',
                    'source': {
                        'type': 'base64',
                        'media_type': attachment.mime_type,
                        'data': base64.b64encode(attachment.data).decode('ascii'),
                    },
                })
            else:
                content.append({'type': 'text', 'text': self.attachment_as_text(attachment)})

        payload = {
            'model': self.model,
            'max_tokens': self.max_tokens,
            'system': system_prompt,
            'messages': [{'role': 'user', 'content': content}],
        }
        headers = {
            'x-api-key': self.api_key,
            'anthropic-version': self.api_version,
            'Content-Type': 'application/json',
        }
        data = self.post_json(f'{self.base_url}/messages', headers, payload)
        try:
            return ''.join(block.get('text', '') for block in data['content'] if block.get('type') == 'text')
        except (KeyError, TypeError) as exc:
            raise ProviderError(f'{self.label}: ساختار پاسخ نامعتبر است') from exc
