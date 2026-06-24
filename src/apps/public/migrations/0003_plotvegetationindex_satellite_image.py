from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('public', '0002_run_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='plotvegetationindex',
            name='satellite_image',
            field=models.ImageField(blank=True, null=True, upload_to='vegetation/'),
        ),
    ]
