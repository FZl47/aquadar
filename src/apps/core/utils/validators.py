import re

from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible


@deconstructible
class PhonenumberValidator:
    message = _('Invalid Phonenumber')
    code = 'invalid_iran_phone'

    def __call__(self, value):
        pattern = re.compile(
            r'^(?:\+98|0098|0)?9\d{9}$'
        )

        if not pattern.match(value):
            raise ValidationError(self.message, code=self.code)
