from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('public', '0022_systemreport_waterman'),
    ]

    operations = [
        migrations.AddField(
            model_name='runstatus',
            name='wind_speed',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True),
        ),
        migrations.AddField(
            model_name='runstatus',
            name='humidity',
            field=models.SmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='runstatus',
            name='weather_fetched',
            field=models.BooleanField(default=False),
        ),
    ]
