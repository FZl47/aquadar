# Generated manually — rename manure models to fertilization (preserve data)

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('public', '0007_fertilization_foliar_spray'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='ManureCategory',
            new_name='FertilizerCategory',
        ),
        migrations.RenameModel(
            old_name='ReportManure',
            new_name='FertilizationRecord',
        ),
        migrations.AlterModelOptions(
            name='fertilizationrecord',
            options={
                'ordering': ('-id',),
                'verbose_name': 'Fertilization Record',
                'verbose_name_plural': 'Fertilization Records',
            },
        ),
        migrations.AlterField(
            model_name='fertilizationrecord',
            name='category',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='records',
                to='public.fertilizercategory',
                verbose_name='Fertilizer Type',
            ),
        ),
        migrations.AlterField(
            model_name='reportfoliarspray',
            name='category',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='records',
                to='public.foliarspraycategory',
                verbose_name='Solution Type',
            ),
        ),
    ]
