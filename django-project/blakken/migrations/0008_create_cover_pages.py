from django.db import migrations
from django.db.models import F


def create_cover_pages(apps, schema_editor):
    Menu = apps.get_model('blakken', 'Menu')
    MenuPage = apps.get_model('blakken', 'MenuPage')
    database = schema_editor.connection.alias

    for menu in Menu.objects.using(database).all():
        pages = list(
            MenuPage.objects.using(database)
            .filter(menu_id=menu.pk)
            .order_by('position', 'pk')
        )
        slugs = {page.slug for page in pages}
        front_slug = 'forside'
        back_slug = 'bakside'
        if front_slug in slugs and back_slug in slugs:
            continue

        cover_image = ''
        overlay = 'black'
        text_shadow = True
        if front_slug not in slugs:
            if pages:
                first_page = pages[0]
                if first_page.layout == 'cover':
                    cover_image = first_page.image.name
                    overlay = first_page.overlay
                    text_shadow = first_page.text_shadow
                    first_page.image = ''
                    first_page.layout = 'split'
                    first_page.save(
                        using=database,
                        update_fields=('image', 'layout'),
                    )

                MenuPage.objects.using(database).filter(menu_id=menu.pk).update(
                    position=F('position') + 1,
                )

            while front_slug in slugs:
                front_slug += '-cover'
            MenuPage.objects.using(database).create(
                menu_id=menu.pk,
                position=0,
                name='Forside',
                slug=front_slug,
                heading=menu.name,
                decorative_title='Velkommen',
                descriptive_title=menu.name[:150],
                content=menu.cover_content,
                image=cover_image,
                layout='cover',
                overlay=overlay,
                text_shadow=text_shadow,
            )
            slugs.add(front_slug)

        if back_slug not in slugs:
            last_position = max((page.position for page in pages), default=0)
            if pages and front_slug not in {page.slug for page in pages}:
                last_position += 1
            while back_slug in slugs:
                back_slug += '-cover'
            back_title = menu.back_cover_title or 'Takk for besøket'
            MenuPage.objects.using(database).create(
                menu_id=menu.pk,
                position=last_position + 1,
                name='Bakside',
                slug=back_slug,
                heading=back_title,
                decorative_title='Vi sees snart',
                descriptive_title=back_title[:150],
                content=menu.back_cover_content,
                layout='cover',
                overlay='black',
                text_shadow=True,
            )
            slugs.add(back_slug)


class Migration(migrations.Migration):

    dependencies = [
        ('blakken', '0007_menupage_overlay_and_text_shadow'),
    ]

    operations = [
        migrations.RunPython(create_cover_pages, migrations.RunPython.noop),
    ]
