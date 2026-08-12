from django.db import migrations, models
from django.utils.text import slugify


def populate_category_slugs(apps, schema_editor):
    Category = apps.get_model('products', 'Category')

    for category in Category.objects.all().order_by('id'):
        if category.slug:
            continue

        base_slug = slugify(category.name) or 'danh-muc'
        candidate_slug = base_slug
        suffix = 1

        while Category.objects.filter(slug=candidate_slug).exclude(pk=category.pk).exists():
            suffix += 1
            candidate_slug = f'{base_slug}-{suffix}'

        category.slug = candidate_slug
        category.save(update_fields=['slug'])


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0006_attribute_management_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='slug',
            field=models.SlugField(blank=True, db_index=True, max_length=50, null=True),
        ),
        migrations.RunPython(populate_category_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='category',
            name='slug',
            field=models.SlugField(blank=True, db_index=True, unique=True),
        ),
        migrations.AlterModelOptions(
            name='category',
            options={
                'ordering': ('name',),
                'verbose_name': 'Danh mục',
                'verbose_name_plural': 'Danh mục',
            },
        ),
    ]
