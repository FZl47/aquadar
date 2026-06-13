from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('public', '0023_runstatus_weather_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='runsettings',
            name='require_gps',
            field=models.BooleanField(default=True, help_text='GPS required for start/end irrigation'),
        ),
        migrations.AddField(
            model_name='runsettings',
            name='allow_code_entry',
            field=models.BooleanField(default=True, help_text='Allow waterman to register irrigation by outlet code'),
        ),
    ]
