from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('public', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='run',
            name='status',
            field=models.CharField(
                choices=[('open', 'Open'), ('closed', 'Closed')],
                db_index=True,
                default='open',
                max_length=8,
                verbose_name='Status',
            ),
        ),
    ]
