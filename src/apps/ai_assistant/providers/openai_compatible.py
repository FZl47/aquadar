import base64

from .base import BaseProvider, ProviderError


class OpenAICompatibleProvider(BaseProvider):
    supports_images = True
    supports_pdf = False

    def generate(self, system_prompt, user_prompt, attachments):
        content = [{'type': 'text', 'text': user_prompt}]
        for attachment in attachments:
            if self.is_native_attachment(attachment):
                encoded = base64.b64encode(attachment.data).decode('ascii')
                content.append({
                    'type': 'text',
                    'text': f'### {attachment.label} ({attachment.filename})',
                })
                content.append({
                    'type': 'image_url',
                    'image_url': {'url': f'data:{attachment.mime_type};base64,{encoded}'},
                })
            else:
                content.append({'type': 'text', 'text': self.attachment_as_text(attachment)})

        payload = {
            'model': self.model,
            'temperature': 0.3,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': content},
            ],
        }
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        data = self.post_json(f'{self.base_url}/chat/completions', headers, payload)
        try:
            return data['choices'][0]['message']['content'] or ''
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f'{self.label}: ساختار پاسخ نامعتبر است') from exc


class ChatGPTProvider(OpenAICompatibleProvider):
    name = 'chatgpt'
    label = 'ChatGPT (OpenAI)'
    default_model = 'gpt-4o'
    default_base_url = 'https://api.openai.com/v1'


class GapGPTProvider(OpenAICompatibleProvider):
    name = 'gapgpt'
    label = 'GapGPT'
    default_model = 'gpt-4o'
    default_base_url = 'https://api.gapgpt.app/v1'


class GrokProvider(OpenAICompatibleProvider):
    name = 'grok'
    label = 'Grok (xAI)'
    default_model = 'grok-4'
    default_base_url = 'https://api.x.ai/v1'


class DeepSeekProvider(OpenAICompatibleProvider):
    name = 'deepseek'
    label = 'DeepSeek'
    supports_images = False
    default_model = 'deepseek-chat'
    default_base_url = 'https://api.deepseek.com'
