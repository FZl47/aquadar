import decimal
import string
import random
import math

from django.conf import settings


def random_str(size=10, chars=string.ascii_lowercase + string.ascii_uppercase + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))


def random_num(size=10, chars=string.digits):
    return ''.join(random.choice(chars) for _ in range(size))


def get_host_url(url):
    return settings.HOST_ADDRESS + url


def get_media_url(url):
    return settings.MEDIA_URL + url


def truncate_float(num):
    # get 2 places of float num
    return math.floor(num * 100) / 100.0


def truncate_decimal(num):
    return decimal.Decimal(num).quantize(decimal.Decimal('0.000'))


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')


def c_bool(str_value):
    """
        convert string bool to pythonic boolean
    """
    if str_value == 'true':
        return True
    return False


def spread_num(number):
    return '{:,}'.format(truncate_decimal(number))


