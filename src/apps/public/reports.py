import jdatetime

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone

from apps.notification.utils import absolute_url, create_user_notif

from .models import RunSettings, SystemReport

PRIORITY_LABELS = {'low': 'کم', 'medium': 'متوسط', 'high': 'بالا'}
SEVERITY_LABELS = {'low': 'کم', 'medium': 'متوسط', 'high': 'زیاد', 'critical': 'بحرانی'}
FIELD_LABELS = {
    'name': 'نام', 'purpose': 'هدف', 'dose': 'مقدار', 'timing': 'زمان', 'method': 'روش',
    'type': 'نوع', 'target': 'هدف مصرف',
}
URGENCY_PRIORITY = {'low': 'low', 'medium': 'medium', 'high': 'high', 'critical': 'high'}
SECTION_TITLES = {
    'status': 'وضعیت شاخص‌ها',
    'findings': 'یافته‌ها',
    'warnings': 'هشدارها',
    'recommendations': 'توصیه‌ها',
    'prevention': 'پیشگیری و اقدامات بعدی',
}


def item_text(item):
    if isinstance(item, dict):
        return '، '.join(
            f'{FIELD_LABELS.get(k, k)}: {v}' for k, v in item.items() if v not in (None, '')
        )
    return '' if item is None else str(item).strip()


def make_section(key, items, title=None):
    texts = [t for t in (item_text(i) for i in (items or [])) if t]
    return {'key': key, 'title': title or SECTION_TITLES.get(key, key), 'items': texts}


def jalali_now():
    return jdatetime.datetime.fromgregorian(datetime=timezone.now()).strftime('%Y/%m/%d %H:%M')


def format_final_report(title, summary='', sections=(), subject='', score=None, priority=None):
    now = jalali_now()
    lines = [f'گزارش نهایی: {title}']
    if subject:
        lines.append(f'موضوع: {subject}')
    lines.append(f'تاریخ گزارش: {now}')
    if priority:
        lines.append(f'اولویت: {PRIORITY_LABELS.get(priority, priority)}')
    if score is not None:
        lines.append(f'امتیاز سلامت: {score} از 100')
    if summary:
        lines.extend(['', '■ خلاصه وضعیت', str(summary).strip()])
    for section in sections:
        if not section['items']:
            continue
        lines.extend(['', f"■ {section['title']}"])
        lines.extend(f'{index}. {text}' for index, text in enumerate(section['items'], start=1))
    return '\n'.join(lines)


def resolve_recipients(farm=None, extra=()):
    User = get_user_model()
    users = []
    if farm is not None:
        users = list(farm.get_supervisors() or [])
    if not users:
        users = list(User.objects.filter(is_active=True).filter(Q(is_superuser=True) | Q(role='supervisor')))
    users.extend(u for u in extra if u is not None)
    unique = {}
    for user in users:
        unique.setdefault(user.pk, user)
    return list(unique.values())


def user_display_name(user):
    if user is None:
        return ''
    return user.get_full_name() or user.username


def operation_recipients(farm=None, actor=None, extra=()):
    return [user for user in resolve_recipients(farm, extra=extra) if actor is None or user.pk != actor.pk]


def min_health_score():
    settings_obj = RunSettings.objects.first()
    if settings_obj is not None and settings_obj.min_health_score is not None:
        return settings_obj.min_health_score
    return 50


def create_system_report(*, category, title, summary, sections, priority, recipients, subject='', score=None,
                         plot=None, outlet=None, waterman=None, link='', notif_type='system_report',
                         notif_extra=None):
    final_report = format_final_report(
        title, summary=summary, sections=sections, subject=subject, score=score, priority=priority)
    report = SystemReport.objects.create(
        waterman=waterman,
        outlet=outlet,
        plot=plot,
        title=str(title)[:256],
        description=str(summary or ''),
        priority=priority,
        category=category,
        final_report=final_report,
        sections=[s for s in sections if s['items']],
        link=str(link or ''),
    )
    report.to_users.set(recipients)
    farm = report.farm
    kwargs_notif = {
        'report_id': report.pk,
        'category': category,
        'category_label': report.get_category_display(),
        'priority': priority,
        'priority_label': PRIORITY_LABELS.get(priority, priority),
        'summary': str(summary or '')[:300],
        'subject': subject,
        'farm': farm.name if farm else '',
        'plot': plot.name if plot else '',
        'score': '' if score is None else str(score),
        'link': absolute_url(link or report.get_absolute_url()),
        'detail_url': absolute_url(report.get_absolute_url()),
    }
    kwargs_notif.update(notif_extra or {})
    for user in recipients:
        create_user_notif(user, notif_type, str(title)[:150], final_report, kwargs_notif=dict(kwargs_notif))
    return report


def plot_priority(health_score, problems, threshold):
    severities = {p.get('severity') for p in problems or [] if isinstance(p, dict)}
    if (health_score is not None and health_score < threshold) or 'high' in severities:
        return 'high'
    if 'medium' in severities or (health_score is not None and health_score < threshold + 20):
        return 'medium'
    return 'low'


def plot_prevention(result):
    items = []
    moisture = result.get('moisture_score')
    greenness = result.get('greenness_score')
    weather = result.get('weather') or {}
    if moisture is not None and moisture < 50:
        items.append('برنامه آبیاری منظم و متناسب با دمای هوا را رعایت کنید و رطوبت خاک را هر چند روز یک‌بار بررسی کنید.')
    if greenness is not None and greenness < 50:
        items.append('پایش دوره‌ای پوشش گیاهی و بازدید میدانی از درختان ضعیف را در برنامه هفتگی قرار دهید.')
    temp = weather.get('temperature_c') if isinstance(weather, dict) else None
    if temp is not None and temp >= 38:
        items.append('در روزهای گرم از آبیاری در ساعات اوج گرما خودداری کنید و آبیاری را به صبح زود یا شب منتقل کنید.')
    if result.get('water_m3') == 0:
        items.append('سامانه آبیاری و سوابق ثبت آبیاری را بررسی کنید تا وقفه طولانی در آبیاری تکرار نشود.')
    if not items:
        items.append('روند فعلی را حفظ کنید و تحلیل بعدی را در موعد زمان‌بندی‌شده بررسی کنید.')
    return items


def build_plot_report(plot, ai_report, result):
    threshold = min_health_score()
    problems = [
        f"{p.get('title', '')} (شدت: {SEVERITY_LABELS.get(p.get('severity'), p.get('severity', ''))}): "
        f"{p.get('description', '')}"
        for p in ai_report.risks or [] if isinstance(p, dict)
    ]
    greenness = result.get('greenness_score')
    moisture = result.get('moisture_score')
    water = result.get('water_m3')
    status = [
        f'سبزینگی: {greenness if greenness is not None else "-"}٪',
        f'رطوبت: {moisture if moisture is not None else "-"}٪',
        f'آب مصرفی ۳۰ روز اخیر: {water if water is not None else "-"} مترمکعب',
    ]
    for key, label in (('ndvi', 'NDVI'), ('ndmi', 'NDMI'), ('ndre', 'NDRE')):
        if result.get(key) is not None:
            status.append(f'{label}: {round(result[key], 3)}')
    irrigation = ai_report.irrigation_assessment
    recommendations = list(ai_report.season_recommendations or [])
    if irrigation:
        recommendations.insert(0, str(irrigation))
    sections = [
        make_section('status', status),
        make_section('warnings', problems),
        make_section('recommendations', recommendations),
        make_section('prevention', plot_prevention(result)),
    ]
    priority = plot_priority(ai_report.health_score, ai_report.risks, threshold)
    return sections, priority
