import base64

from .base import BaseProvider, ProviderError


class GeminiProvider(BaseProvider):
    name = 'gemini'
    label = 'Gemini (Google)'
    supports_images = True
    supports_pdf = True
    default_model = 'gemini-2.5-flash'
    default_base_url = 'https://generativelanguage.googleapis.com/v1beta'
    max_output_tokens = 16384

    def generate(self, system_prompt, user_prompt, attachments):
        parts = [{'text': user_prompt}]
        for attachment in attachments:
            if self.is_native_attachment(attachment):
                parts.append({'text': f'### {attachment.label} ({attachment.filename})'})
                parts.append({
                    'inlineData': {
                        'mimeType': attachment.mime_type,
                        'data': base64.b64encode(attachment.data).decode('ascii'),
                    },
                })
            else:
                parts.append({'text': self.attachment_as_text(attachment)})

        payload = {
            'systemInstruction': {'parts': [{'text': system_prompt}]},
            'contents': [{'role': 'user', 'parts': parts}],
            'generationConfig': {
                'temperature': 0.3,
                'maxOutputTokens': self.max_output_tokens,
                'responseMimeType': 'application/json',
            },
        }
        headers = {
            'x-goog-api-key': self.api_key,
            'Content-Type': 'application/json',
        }
        data = self.post_json(f'{self.base_url}/models/{self.model}:generateContent', headers, payload)
        try:
            candidate = data['candidates'][0]
            return ''.join(part.get('text', '') for part in candidate['content']['parts'])
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(f'{self.label}: ساختار پاسخ نامعتبر است') from exc
