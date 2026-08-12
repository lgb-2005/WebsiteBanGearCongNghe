# Generated migration to remove Order.user field for Single Source of Truth

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0008_sync_order_user_to_customer'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='order',
            name='user',
        ),
    ]
