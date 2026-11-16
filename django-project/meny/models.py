from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.text import slugify


ALLERGEN_CHOICES = (
    ('gluten', 'Gluten'),
    ('crustaceans', 'Skalldyr'),
    ('eggs', 'Egg'),
    ('fish', 'Fisk'),
    ('peanuts', 'Peanøtter'),
    ('soybeans', 'Soya'),
    ('milk', 'Melk'),
    ('nuts', 'Nøtter'),
    ('celery', 'Selleri'),
    ('mustard', 'Sennep'),
    ('sesame', 'Sesamfrø'),
    ('sulphites', 'Sulfitter'),
    ('lupin', 'Lupin'),
    ('molluscs', 'Bløtdyr'),
)

PAGE_SLUG_SUFFIXES = ('to', 'tre', 'fire', 'fem', 'seks', 'sju', 'atte', 'ni', 'ti')


def unique_page_slug(base, reserved):
    slug = base
    suffix = 2
    while slug in reserved:
        word = (
            PAGE_SLUG_SUFFIXES[suffix - 2]
            if suffix - 2 < len(PAGE_SLUG_SUFFIXES) else str(suffix)
        )
        slug = f'{base[:160 - len(word) - 1]}-{word}'
        suffix += 1
    return slug


class Job(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    task_id = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at', '-pk')


class ShopStatus(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    is_open = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(pk=1), name='single_shop_status'),
        ]


class Menu(models.Model):
    name = models.CharField(max_length=150)
    show_toc = models.BooleanField(default=True)
    max_per_page = models.PositiveIntegerField(
        default=4, null=True, blank=True, validators=[MinValueValidator(1)],
        verbose_name='Max dishes per first page',
        help_text='Menu-wide limit. Leave either limit blank to use manual pages only.',
    )
    max_per_extra_page = models.PositiveIntegerField(
        default=5, null=True, blank=True, validators=[MinValueValidator(1)],
        verbose_name='Max dishes per extra page',
        help_text='Applies to automatic and manual continuation pages.',
    )
    content = models.TextField(blank=True)
    description = models.TextField(blank=True, verbose_name='Introduction')
    cover_content = models.TextField(blank=True, verbose_name='Front cover text')
    back_cover_title = models.CharField(max_length=200, blank=True)
    back_cover_content = models.TextField(blank=True, verbose_name='Back cover text')

    class Meta:
        ordering = ('name', 'pk')

    def __str__(self):
        return self.name


class MenuPage(models.Model):
    class Layout(models.TextChoices):
        PANORAMA = 'panorama', 'Panorama'
        COVER = 'cover', 'Cover'
        SPLIT = 'split', 'Split'

    class Overlay(models.TextChoices):
        BLACK = 'black', 'Black'
        WHITE = 'white', 'White'
        NONE = 'none', 'None'

    menu = models.ForeignKey(Menu, on_delete=models.CASCADE, related_name='pages')
    position = models.PositiveIntegerField(default=0, db_index=True)
    is_visible = models.BooleanField(default=True, verbose_name='Visible to customers')
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=160, blank=True)
    is_continuation = models.BooleanField(
        default=False,
        verbose_name='Continuation page',
        help_text='Show the feelgood heading and dishes only; omit the category title and contents entry.',
    )
    heading = models.CharField(
        max_length=200, blank=True,
        help_text='Required except on continuation pages.',
    )
    decorative_title = models.CharField(max_length=150)
    descriptive_title = models.CharField(max_length=150, blank=True)
    content = models.TextField(blank=True)
    image = models.ImageField(upload_to='menus/pages/', blank=True)
    layout = models.CharField(max_length=10, choices=Layout.choices, default=Layout.SPLIT)
    overlay = models.CharField(max_length=5, choices=Overlay.choices, default=Overlay.BLACK)
    text_shadow = models.BooleanField(default=False)

    class Meta:
        ordering = ('position', 'pk')
        constraints = (
            models.UniqueConstraint(fields=('menu', 'slug'), name='unique_menu_page_slug'),
        )

    def unique_slug(self, base=None, reserved=()):
        base = base or self.slug or slugify(self.name) or 'page'
        pages = type(self).objects.filter(menu_id=self.menu_id).exclude(pk=self.pk)
        return unique_page_slug(base, set(pages.values_list('slug', flat=True)) | set(reserved))

    def clean(self):
        super().clean()
        errors = {}
        if not self.is_continuation and not self.heading:
            errors['heading'] = 'Enter a heading or mark this as a continuation page.'
        if self.is_continuation and self.layout == self.Layout.COVER:
            errors['is_continuation'] = 'Cover pages cannot be continuation pages.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.slug = self.unique_slug()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


def menu_page_groups(pages):
    groups = []
    for page in pages[1:-1]:
        if page.is_continuation and groups and groups[-1][0].layout != MenuPage.Layout.COVER:
            groups[-1].append(page)
        else:
            groups.append([page])
    return groups


def visible_menu_pages(pages):
    visible = []
    category_visible = True
    for page in pages:
        if not page.is_continuation or page.layout == MenuPage.Layout.COVER:
            category_visible = page.is_visible
        if category_visible and page.is_visible:
            visible.append(page)
    return visible


class Dish(models.Model):
    menu_page = models.ForeignKey(MenuPage, on_delete=models.CASCADE, related_name='dishes')
    position = models.PositiveIntegerField(default=0)
    is_visible = models.BooleanField(default=True, verbose_name='Visible to customers')
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    allergens = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ('position', 'pk')

    def __str__(self):
        return self.name


class Order(models.Model):
    class Status(models.TextChoices):
        NEW = 'new', 'Ny'
        PREPARING = 'preparing', 'Tilberedes'
        READY = 'ready', 'Klar'
        COMPLETED = 'completed', 'Fullført'
        CANCELLED = 'cancelled', 'Kansellert'

    menu = models.ForeignKey(Menu, null=True, on_delete=models.SET_NULL)
    menu_name = models.CharField(max_length=150)
    submission_id = models.UUIDField(unique=True, editable=False)
    request_fingerprint = models.CharField(max_length=64, editable=False)
    customer_channel = models.UUIDField(null=True, editable=False, db_index=True)
    customer_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=32)
    note = models.TextField(blank=True, max_length=2000)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW, db_index=True)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at', '-pk')


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    dish = models.ForeignKey(Dish, null=True, on_delete=models.SET_NULL)
    name = models.CharField(max_length=150)
    quantity = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)

    class Meta:
        ordering = ('pk',)
