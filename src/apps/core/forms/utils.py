from django.utils.translation import gettext_lazy as _
from django.contrib import messages


def form_validate_err(request, form):

    if form.is_valid():
        return True

    errors = form.errors.as_data()
    if not errors:
        messages.error(request, _('Incorrect Data'))
        return False

    for field, err in errors.items():
        err = str(err[0])
        err = err.replace('[', '').replace(']', '')
        err = err.replace("'", '').replace('This', '')
        err = f'{field} {err}'
        messages.error(request, err)

    return False
