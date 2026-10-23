from django.db import migrations
from django.db.models import OuterRef, Subquery


def backfill_plot(apps, schema_editor):
    SystemReport = apps.get_model('public', 'SystemReport')
    Outlet = apps.get_model('public', 'Outlet')
    SystemReport.objects.filter(plot__isnull=True, outlet__isnull=False).update(
        plot=Subquery(Outlet.objects.filter(pk=OuterRef('outlet_id')).values('plot_id')[:1])
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('public', '0013_plotaireport_final_report_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_plot, noop_reverse),
    ]
