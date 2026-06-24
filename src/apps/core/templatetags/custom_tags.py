import jdatetime

from django import template
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag
def aq_breadcrumb(*items):
    """Render breadcrumbs from positional ``"Name|url_name"`` strings.

    URL name is optional. Last item is rendered as active (no link).
    Usage: ``{% aq_breadcrumb "Farms|public:farm_list" "Detail" %}``
    """
    if not items:
        return ''
    parts = []
    for raw in items:
        if raw is None:
            continue
        text = str(raw)
        name, _, url_name = text.partition('|')
        href = ''
        if url_name:
            try:
                href = reverse(url_name)
            except NoReverseMatch:
                href = url_name
        parts.append((name.strip(), href))

    home = format_html(
        '<li><a href="{}"><i class="fa fa-home"></i> داشبورد</a></li>',
        reverse('public:index') if _safe_reverse('public:index') else '/',
    )
    rendered = [home]
    last = len(parts) - 1
    for i, (name, href) in enumerate(parts):
        rendered.append(mark_safe('<li class="aq-bc-sep" aria-hidden="true">/</li>'))
        if href and i != last:
            rendered.append(format_html('<li><a href="{}">{}</a></li>', href, name))
        else:
            rendered.append(format_html('<li class="aq-bc-active" aria-current="page">{}</li>', name))

    return mark_safe(
        '<nav aria-label="breadcrumb" class="aq-breadcrumb-wrap">'
        '<ol class="aq-breadcrumb">' + ''.join(str(x) for x in rendered) + '</ol></nav>'
    )


def _safe_reverse(name):
    try:
        return reverse(name)
    except NoReverseMatch:
        return None


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
