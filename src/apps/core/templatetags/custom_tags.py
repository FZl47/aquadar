import jdatetime

from django import template

register = template.Library()


@register.simple_tag
def call(obj, method_name, *args, **kwargs):
    return getattr(obj, method_name)(*args, **kwargs)


@register.filter
def jalali(value, format_str='%Y/%m/%d %H:%M'):
    if not value:
        return ''
    try:
        return jdatetime.datetime.fromgregorian(datetime=value).strftime(format_str)
    except Exception:
        return str(value)


@register.filter
def jalali_date(value):
    if not value:
        return ''
    try:
        return jdatetime.date.fromgregorian(date=value).strftime('%Y/%m/%d')
    except Exception:
        return str(value)
