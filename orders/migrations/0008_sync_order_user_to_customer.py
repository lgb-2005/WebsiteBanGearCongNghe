# Generated migration for syncing Order.user to Customer.user

from django.db import migrations, transaction
from django.db.models import F


def sync_order_user_to_customer(apps, schema_editor):
    """
    Sync Order.user from Customer.user for consistency during transition.
    This ensures existing queries continue to work while we migrate to single source of truth.
    """
    Order = apps.get_model('orders', 'Order')
    
    with transaction.atomic():
        # Find orders where customer.user is NOT NULL but order.user is NULL
        # These are the cases we need to sync to maintain consistency during transition
        orders_to_sync = Order.objects.filter(
            customer__user__isnull=False,
            user__isnull=True
        )
        
        count = 0
        for order in orders_to_sync:
            # Update the order to match the customer.user
            Order.objects.filter(pk=order.pk).update(
                user=order.customer.user
            )
            count += 1
        
        print(f"Synced {count} orders: updated Order.user from Customer.user")


def reverse_sync(apps, schema_editor):
    """
    Reverse migration - no action needed as this is data synchronization
    """
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0007_customer_phone_db_index'),
    ]

    operations = [
        migrations.RunPython(sync_order_user_to_customer, reverse_sync),
    ]
