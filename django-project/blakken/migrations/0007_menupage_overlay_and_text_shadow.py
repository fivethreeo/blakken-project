from django.db import migrations, models


def enable_text_shadows_for_image_pages(apps, schema_editor):
    MenuPage = apps.get_model('blakken', 'MenuPage')
    pages_by_menu = {}
    pages = MenuPage.objects.using(schema_editor.connection.alias).order_by(
        'menu_id', 'position', 'pk',
    )
    for page in pages:
        pages_by_menu.setdefault(page.menu_id, []).append(page)

    for menu_pages in pages_by_menu.values():
        last_index = len(menu_pages) - 1
        for index, page in enumerate(menu_pages):
            use_shadow = index in (0, last_index) or page.layout == 'panorama'
            if (
                not use_shadow
                and 0 < index < last_index
                and menu_pages[index - 1].layout == 'panorama'
                and menu_pages[index - 1].image
                and not page.image
            ):
                use_shadow = True
            if use_shadow:
                page.text_shadow = True
                page.save(using=schema_editor.connection.alias, update_fields=['text_shadow'])


class Migration(migrations.Migration):

    dependencies = [
        ('blakken', '0006_menu_content'),
    ]

    operations = [
        migrations.AddField(
            model_name='menupage',
            name='overlay',
            field=models.CharField(
                choices=[('black', 'Black'), ('white', 'White'), ('none', 'None')],
                default='black',
                max_length=5,
            ),
        ),
        migrations.AddField(
            model_name='menupage',
            name='text_shadow',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(enable_text_shadows_for_image_pages, migrations.RunPython.noop),
    ]
