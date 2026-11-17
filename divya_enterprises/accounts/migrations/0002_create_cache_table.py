"""Create the database cache table (settings.CACHES) as part of migrate.

Login throttling stores its counters in this table. Running it from a
migration means a plain "python manage.py migrate" on any machine (the shop
PC included) leaves login working; "createcachetable" stays safe to run as
well, since both skip a table that already exists.
"""

from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    call_command("createcachetable", database=schema_editor.connection.alias, verbosity=0)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_cache_table, migrations.RunPython.noop),
    ]
