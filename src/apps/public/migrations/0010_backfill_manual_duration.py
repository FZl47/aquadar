# Backfill ManualIrrigation.duration_seconds from start/end window for existing rows.

from django.db import migrations


def backfill_duration(apps, schema_editor):
    ManualIrrigation = apps.get_model('public', 'ManualIrrigation')
    for mi in ManualIrrigation.objects.all().iterator():
        if not mi.start_datetime or not mi.end_datetime:
            continue
        secs = max(0, int((mi.end_datetime - mi.start_datetime).total_seconds()))
        if mi.duration_seconds != secs:
            mi.duration_seconds = secs
            mi.save(update_fields=['duration_seconds'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('public', '0009_due_date_and_manual_duration'),
    ]

    operations = [
        migrations.RunPython(backfill_duration, noop_reverse),
    ]
