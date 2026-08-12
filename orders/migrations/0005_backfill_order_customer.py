from django.db import migrations


def _normalize_email(email):
    return (email or '').strip().lower()


def backfill_order_customer(apps, schema_editor):
    Order = apps.get_model('orders', 'Order')
    Customer = apps.get_model('orders', 'Customer')

    for order in Order.objects.select_related('user').all().iterator():
        user = getattr(order, 'user', None)
        normalized_email = _normalize_email(
            getattr(order, 'receiver_email', '')
            or getattr(user, 'email', '')
        )
        full_name = (
            getattr(order, 'receiver_name', '')
            or getattr(user, 'name', '')
            or ''
        ).strip()
        phone = (
            getattr(order, 'receiver_phone', '')
            or getattr(user, 'phone', '')
            or ''
        ).strip()

        customer = None

        if order.user_id:
            customer = Customer.objects.filter(user_id=order.user_id).order_by('id').first()

        if customer is None and normalized_email:
            customer = Customer.objects.filter(email__iexact=normalized_email).order_by('id').first()

        if customer is None:
            customer = Customer.objects.create(
                user_id=order.user_id,
                full_name=full_name,
                email=normalized_email,
                phone=phone,
            )
        else:
            update_fields = []

            if customer.user_id is None and order.user_id:
                customer.user_id = order.user_id
                update_fields.append('user')

            if full_name and not customer.full_name:
                customer.full_name = full_name
                update_fields.append('full_name')

            if normalized_email and not customer.email:
                customer.email = normalized_email
                update_fields.append('email')

            if phone and not customer.phone:
                customer.phone = phone
                update_fields.append('phone')

            if update_fields:
                customer.save(update_fields=update_fields)

        if order.customer_id != customer.id:
            order.customer_id = customer.id
            order.save(update_fields=['customer'])


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0004_customer_order_customer'),
    ]

    operations = [
        migrations.RunPython(backfill_order_customer, migrations.RunPython.noop),
    ]
