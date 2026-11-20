from django.db import migrations, models
from django.utils.text import slugify


def populate_page_names_and_menu_copy(apps, schema_editor):
    Menu = apps.get_model('blakken', 'Menu')
    MenuPage = apps.get_model('blakken', 'MenuPage')
    database = schema_editor.connection.alias

    for menu in Menu.objects.using(database).all():
        menu.description = menu.description or 'Utforsk blakkenen og finn din neste favoritt.'
        menu.cover_content = menu.cover_content or 'Velkommen. Bla gjennom blakkenen og finn noe godt.'
        menu.back_cover_title = menu.back_cover_title or 'Takk for besøket'
        menu.back_cover_content = menu.back_cover_content or 'Vi håper du hadde et godt måltid.'
        menu.save(
            using=database,
            update_fields=(
                'description', 'cover_content', 'back_cover_title', 'back_cover_content',
            ),
        )

    slugs_by_menu = {}
    for page in MenuPage.objects.using(database).order_by('menu_id', 'pk'):
        page.name = page.heading
        page.descriptive_title = page.heading
        base_slug = slugify(page.name) or f'page-{page.pk}'
        slug = base_slug
        suffix = 2
        slugs = slugs_by_menu.setdefault(page.menu_id, set())
        while slug in slugs:
            slug = f'{base_slug}-{suffix}'
            suffix += 1
        slugs.add(slug)
        page.slug = slug
        page.save(
            using=database,
            update_fields=('name', 'slug', 'descriptive_title'),
        )


class Migration(migrations.Migration):

    dependencies = [
        ('blakken', '0003_alter_menupage_position'),
    ]

    operations = [
        migrations.AddField(
            model_name='menu',
            name='description',
            field=models.TextField(blank=True, default='', verbose_name='Introduction'),
        ),
        migrations.AddField(
            model_name='menu',
            name='cover_content',
            field=models.TextField(blank=True, default='', verbose_name='Front cover text'),
        ),
        migrations.AddField(
            model_name='menu',
            name='back_cover_title',
            field=models.CharField(blank=True, default='', max_length=200),
        ),
        migrations.AddField(
            model_name='menu',
            name='back_cover_content',
            field=models.TextField(blank=True, default='', verbose_name='Back cover text'),
        ),
        migrations.AddField(
            model_name='menupage',
            name='name',
            field=models.CharField(blank=True, default='', max_length=150),
        ),
        migrations.AddField(
            model_name='menupage',
            name='slug',
            field=models.SlugField(blank=True, default='', max_length=160),
        ),
        migrations.AddField(
            model_name='menupage',
            name='descriptive_title',
            field=models.CharField(blank=True, default='', max_length=150),
        ),
        migrations.RunPython(populate_page_names_and_menu_copy, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='menu',
            name='description',
            field=models.TextField(blank=True, verbose_name='Introduction'),
        ),
        migrations.AlterField(
            model_name='menu',
            name='cover_content',
            field=models.TextField(blank=True, verbose_name='Front cover text'),
        ),
        migrations.AlterField(
            model_name='menu',
            name='back_cover_title',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AlterField(
            model_name='menu',
            name='back_cover_content',
            field=models.TextField(blank=True, verbose_name='Back cover text'),
        ),
        migrations.AlterField(
            model_name='menupage',
            name='name',
            field=models.CharField(max_length=150),
        ),
        migrations.AlterField(
            model_name='menupage',
            name='slug',
            field=models.SlugField(blank=True, max_length=160),
        ),
        migrations.AlterField(
            model_name='menupage',
            name='descriptive_title',
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.AlterField(
            model_name='menupage',
            name='heading',
            field=models.CharField(max_length=200, verbose_name='Decorative title'),
        ),
        migrations.AddConstraint(
            model_name='menupage',
            constraint=models.UniqueConstraint(
                fields=('menu', 'slug'),
                name='unique_menu_page_slug',
            ),
        ),
    ]
