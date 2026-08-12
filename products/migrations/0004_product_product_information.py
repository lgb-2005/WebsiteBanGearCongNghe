from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0003_productimage'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='product_information',
            field=models.TextField(blank=True),
        ),
    ]
