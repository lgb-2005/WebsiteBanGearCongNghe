from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('products', '0004_product_product_information'),
    ]

    operations = [
        migrations.CreateModel(
            name='AttributeGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('slug', models.SlugField(db_index=True, unique=True)),
                ('is_filterable', models.BooleanField(default=True)),
                ('display_order', models.PositiveIntegerField(default=0)),
                ('filter_type', models.CharField(choices=[('checkbox', 'Checkbox'), ('radio', 'Radio'), ('select', 'Select'), ('color', 'Color'), ('range', 'Range')], max_length=20)),
                ('data_type', models.CharField(choices=[('text', 'Text'), ('number', 'Number'), ('boolean', 'Boolean')], max_length=20)),
            ],
            options={
                'verbose_name': 'Nhóm thuộc tính',
                'verbose_name_plural': 'Nhóm thuộc tính',
                'ordering': ('display_order', 'name'),
                'indexes': [models.Index(fields=['display_order', 'name'], name='products_at_display_f9d263_idx'), models.Index(fields=['is_filterable', 'display_order'], name='products_at_is_filt_92af1f_idx')],
            },
        ),
        migrations.CreateModel(
            name='AttributeValue',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('value', models.CharField(db_index=True, max_length=150)),
                ('slug', models.SlugField(blank=True, db_index=True)),
                ('group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='values', to='products.attributegroup')),
            ],
            options={
                'verbose_name': 'Giá trị thuộc tính',
                'verbose_name_plural': 'Giá trị thuộc tính',
                'ordering': ('group_id', 'value'),
                'indexes': [models.Index(fields=['group', 'slug'], name='products_at_group_i_45ef3d_idx'), models.Index(fields=['group', 'value'], name='products_at_group_i_6cb628_idx')],
            },
        ),
        migrations.CreateModel(
            name='ProductAttribute',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('custom_value', models.CharField(blank=True, max_length=200, null=True)),
                ('attribute_value', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='products.attributevalue')),
                ('product', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attributes', to='products.product')),
            ],
            options={
                'verbose_name': 'Thuộc tính sản phẩm',
                'verbose_name_plural': 'Thuộc tính sản phẩm',
                'ordering': ('product_id', 'attribute_value_id'),
                'indexes': [models.Index(fields=['product', 'attribute_value'], name='products_pr_product__616965_idx'), models.Index(fields=['attribute_value', 'product'], name='products_pr_attribu_278491_idx')],
            },
        ),
        migrations.AddField(
            model_name='attributegroup',
            name='categories',
            field=models.ManyToManyField(blank=True, related_name='attribute_groups', to='products.category'),
        ),
        migrations.AddConstraint(
            model_name='attributevalue',
            constraint=models.UniqueConstraint(fields=('group', 'value'), name='unique_attribute_value_per_group'),
        ),
        migrations.AddConstraint(
            model_name='attributevalue',
            constraint=models.UniqueConstraint(fields=('group', 'slug'), name='unique_attribute_slug_per_group'),
        ),
        migrations.AddConstraint(
            model_name='productattribute',
            constraint=models.UniqueConstraint(fields=('product', 'attribute_value'), name='unique_product_attribute'),
        ),
    ]
