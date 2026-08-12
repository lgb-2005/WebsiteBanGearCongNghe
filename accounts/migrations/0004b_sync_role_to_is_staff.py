from django.db import migrations


def sync_role_to_is_staff(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.filter(role='admin', is_staff=False).update(is_staff=True)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_rename_address_user_street_address_and_more'),
    ]

    operations = [
        migrations.RunPython(sync_role_to_is_staff, migrations.RunPython.noop),
    ]
