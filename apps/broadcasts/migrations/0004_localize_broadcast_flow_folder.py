from django.db import migrations


def rename_broadcast_folder(apps, schema_editor):
    Flow = apps.get_model("flows", "Flow")
    alias = schema_editor.connection.alias
    Flow._base_manager.using(alias).filter(broadcasts__isnull=False, folder="Broadcasts").update(folder="Disparos")


def restore_broadcast_folder(apps, schema_editor):
    Flow = apps.get_model("flows", "Flow")
    alias = schema_editor.connection.alias
    Flow._base_manager.using(alias).filter(broadcasts__isnull=False, folder="Disparos").update(folder="Broadcasts")


class Migration(migrations.Migration):
    dependencies = [
        ("broadcasts", "0003_broadcast_send_time_chosen"),
        ("flows", "0007_flow_offline"),
    ]

    operations = [
        migrations.RunPython(rename_broadcast_folder, restore_broadcast_folder),
    ]
