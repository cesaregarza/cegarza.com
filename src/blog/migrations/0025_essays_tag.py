from django.db import migrations


def create_essays_tag(apps, schema_editor):
    BlogTag = apps.get_model("blog", "BlogTag")
    BlogTag.objects.using(schema_editor.connection.alias).get_or_create(
        slug="essays",
        defaults={
            "name": "Essays",
            "description": "Personal essays, reflections, and longer-form writing.",
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("blog", "0024_blogpage_force_math"),
    ]

    operations = [
        # Keep the editorial tag and any assignments when rolling code back.
        migrations.RunPython(create_essays_tag, migrations.RunPython.noop),
    ]
