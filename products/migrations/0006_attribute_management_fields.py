from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0005_attribute_system'),
    ]

    operations = [
        migrations.AddField(
            model_name='attributegroup',
            name='is_active',
            field=models.BooleanField(db_index=True, default=True),
        ),
        migrations.AddField(
            model_name='attributevalue',
            name='display_order',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='attributevalue',
            name='hex_color',
            field=models.CharField(blank=True, max_length=7),
        ),
        migrations.AddField(
            model_name='attributevalue',
            name='is_active',
            field=models.BooleanField(db_index=True, default=True),
        ),
        migrations.AlterModelOptions(
            name='attributevalue',
            options={
                'ordering': ('group__display_order', 'group__name', 'display_order', 'value'),
                'verbose_name': 'Giá trị thuộc tính',
                'verbose_name_plural': 'Giá trị thuộc tính',
            },
        ),
        migrations.AddIndex(
            model_name='attributegroup',
            index=models.Index(fields=['is_active', 'display_order'], name='products_at_is_acti_a8fb54_idx'),
        ),
        migrations.AddIndex(
            model_name='attributevalue',
            index=models.Index(fields=['group', 'is_active', 'display_order'], name='products_at_group_i_7dd0ec_idx'),
        ),
    ]
