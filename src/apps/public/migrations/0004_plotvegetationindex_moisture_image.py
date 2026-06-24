from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('public', '0003_plotvegetationindex_satellite_image'),
    ]

    operations = [
        migrations.AddField(
            model_name='plotvegetationindex',
            name='moisture_image',
            field=models.ImageField(blank=True, null=True, upload_to='vegetation/'),
        ),
    ]
