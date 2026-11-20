from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blakken', '0005_menupage_decorative_title'),
    ]

    operations = [
        migrations.AddField(
            model_name='menu',
            name='content',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AlterField(
            model_name='menu',
            name='content',
            field=models.TextField(blank=True),
        ),
    ]
