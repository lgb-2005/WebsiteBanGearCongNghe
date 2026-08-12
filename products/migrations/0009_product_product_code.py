import random
import string

from django.db import migrations, models


def _gen_code(existing):
    charset = string.ascii_uppercase + string.digits
    while True:
        code = 'SP' + ''.join(random.choices(charset, k=7))
        if code not in existing:
            return code


def populate_product_codes(apps, schema_editor):
    Product = apps.get_model('products', 'Product')
    existing = set(
        Product.objects.exclude(product_code__isnull=True)
        .exclude(product_code='')
        .values_list('product_code', flat=True)
    )
    products_to_update = []
    for product in Product.objects.filter(
        models.Q(product_code__isnull=True) | models.Q(product_code='')
    ):
        code = _gen_code(existing)
        existing.add(code)
        product.product_code = code
        products_to_update.append(product)

    if products_to_update:
        Product.objects.bulk_update(products_to_update, ['product_code'])


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0008_favorite_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='product_code',
            field=models.CharField(blank=True, default='', editable=False, max_length=9),
            preserve_default=False,
        ),
        migrations.RunPython(populate_product_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='product',
            name='product_code',
            field=models.CharField(
                db_index=True,
                editable=False,
                max_length=9,
                unique=True,
            ),
        ),
    ]
