# Generated by Django 3.2.19 on 2023-07-28 13:33

from django.db import migrations
from django.core.management import call_command


def load_language_taxonomy(apps, schema_editor):
    """
    Load language taxonomy and tags
    """
    call_command("loaddata", "--app=oel_tagging", "language_taxonomy.yaml")


def revert(apps, schema_editor):
    """
    Deletes language taxonomy an tags
    """
    Taxonomy = apps.get_model("oel_tagging", "Taxonomy")
    Taxonomy.objects.filter(id=-1).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("oel_tagging", "0004_auto_20230723_2001"),
    ]

    operations = [
        migrations.RunPython(load_language_taxonomy, revert),
    ]
