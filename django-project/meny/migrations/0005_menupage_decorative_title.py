from django.db import migrations, models


def populate_decorative_titles(apps, schema_editor):
    MenuPage = apps.get_model('meny', 'MenuPage')
    database = schema_editor.connection.alias
    titles = {
        'smaretter': 'Små biter, store smil',
        'curry': 'Varme krydder, gode øyeblikk',
        'tandoor-og-tilbehr': 'Del gode smaker',
        'dessert-og-drikke': 'Søt avslutning, gode minner',
    }

    for page in MenuPage.objects.using(database).all():
        page.decorative_title = titles.get(page.slug, 'God mat, godt humør')
        page.save(using=database, update_fields=('decorative_title',))


class Migration(migrations.Migration):

    dependencies = [
        ('meny', '0004_menu_page_names_and_copy'),
    ]

    operations = [
        migrations.AddField(
            model_name='menupage',
            name='decorative_title',
            field=models.CharField(blank=True, default='', max_length=150),
        ),
        migrations.RunPython(populate_decorative_titles, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='menupage',
            name='decorative_title',
            field=models.CharField(max_length=150),
        ),
        migrations.AlterField(
            model_name='menupage',
            name='heading',
            field=models.CharField(max_length=200),
        ),
    ]
