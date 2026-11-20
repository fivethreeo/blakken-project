from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _
from uuid import uuid4


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


class Restaurant(models.Model):
    name = models.CharField(_('Restaurant name'), max_length=150)
    active = models.BooleanField(_('Active'), default=False)
    require_verified_orders = models.BooleanField(
        _('Require verified app orders'), default=True,
        help_text=_('Disable explicitly to allow web, SideStore, or debug-client orders.'),
    )
    appid = models.UUIDField(_('App ID'), default=uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(_('Created at'), auto_now_add=True)

    class Meta:
        ordering = ('name', 'pk')

    def __str__(self):
        return self.name


class RestaurantMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = 'owner', _('Owner')
        MANAGER = 'manager', _('Manager')

    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name='memberships',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='restaurant_memberships',
    )
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.OWNER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=('restaurant', 'user'), name='unique_restaurant_membership',
            ),
        ]


class NativeAppRegistration(models.Model):
    class Platform(models.TextChoices):
        IOS = 'ios', 'iOS'
        ANDROID = 'android', 'Android'

    class Role(models.TextChoices):
        CUSTOMER = 'customer', 'Customer'
        MANAGEMENT = 'management', 'Management'

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    name = models.CharField(max_length=150)
    platform = models.CharField(max_length=7, choices=Platform.choices)
    role = models.CharField(max_length=10, choices=Role.choices)
    restaurant = models.ForeignKey(
        Restaurant, null=True, blank=True, on_delete=models.CASCADE,
        related_name='native_apps',
    )
    app_id = models.CharField(
        max_length=255,
        help_text='Apple App ID prefix + bundle ID on iOS; package name on Android.',
    )
    certificate_digests = models.JSONField(
        default=list, blank=True,
        help_text='Android Play App Signing SHA-256 digests as a JSON list of base64url strings.',
    )
    enabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(role='customer', restaurant__isnull=False)
                    | Q(role='management', restaurant__isnull=True)
                ),
                name='native_app_restaurant_matches_role',
            ),
            models.UniqueConstraint(
                fields=('platform', 'app_id'), name='unique_native_app_identity',
            ),
        ]

    def clean(self):
        super().clean()
        if (self.role == self.Role.CUSTOMER) != bool(self.restaurant_id):
            raise ValidationError('Customer apps require a restaurant; management apps must not have one.')
        if not isinstance(self.certificate_digests, list):
            raise ValidationError({'certificate_digests': 'Expected a JSON list of certificate digests.'})
        if self.platform == self.Platform.ANDROID:
            from .play_integrity import normalize_certificate_digest
            if (
                (self.enabled and not self.certificate_digests)
                or any(normalize_certificate_digest(value) is None for value in self.certificate_digests)
            ):
                raise ValidationError({
                    'certificate_digests': 'Provide base64url SHA-256 Play App Signing certificate digests.',
                })

    def __str__(self):
        return self.name


class RefreshToken(models.Model):
    jti = models.UUIDField(unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='api_refresh_tokens',
    )
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    app_registration = models.ForeignKey(
        NativeAppRegistration, null=True, blank=True, on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)


class AppAttestChallenge(models.Model):
    class Purpose(models.TextChoices):
        ATTESTATION = 'attestation', 'Attestation'
        ASSERTION = 'assertion', 'Assertion'

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    customer_channel = models.UUIDField(db_index=True)
    app_registration = models.ForeignKey(
        NativeAppRegistration, null=True, blank=True, on_delete=models.CASCADE,
    )
    purpose = models.CharField(max_length=12, choices=Purpose.choices)
    challenge = models.BinaryField(max_length=32)
    request_hash = models.CharField(max_length=64, blank=True)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AppAttestKey(models.Model):
    class Environment(models.TextChoices):
        PRODUCTION = 'production', 'Production'

    key_id = models.CharField(max_length=64, unique=True)
    customer_channel = models.UUIDField(db_index=True)
    app_registration = models.ForeignKey(
        NativeAppRegistration, null=True, blank=True, on_delete=models.CASCADE,
    )
    public_key = models.TextField()
    app_id = models.CharField(max_length=255)
    bundle_version = models.CharField(max_length=64)
    validation_category = models.PositiveSmallIntegerField()
    environment = models.CharField(max_length=12, choices=Environment.choices)
    counter = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class PlayIntegrityChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    customer_channel = models.UUIDField(db_index=True)
    app_registration = models.ForeignKey(
        NativeAppRegistration, null=True, blank=True, on_delete=models.CASCADE,
    )
    challenge = models.BinaryField(max_length=32)
    request_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField(db_index=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ShopStatus(models.Model):
    id = models.AutoField(primary_key=True)
    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name='shop_statuses',
    )
    is_open = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=('restaurant',), name='unique_restaurant_shop_status'),
        ]


class Menu(models.Model):
    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.CASCADE, related_name='menus',
    )
    name = models.CharField(max_length=150)
    is_default = models.BooleanField(_('Default menu'), default=False)
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
        constraints = [
            models.UniqueConstraint(
                fields=('restaurant',), condition=Q(is_default=True),
                name='unique_default_menu_per_restaurant',
            ),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.restaurant_id:
            with transaction.atomic():
                other_menus = type(self).objects.filter(restaurant_id=self.restaurant_id).exclude(
                    pk=self.pk,
                )
                if not other_menus.exists():
                    self.is_default = True
                elif not self.is_default and self.pk and not other_menus.filter(
                    is_default=True,
                ).exists():
                    self.is_default = True
                if self.is_default:
                    other_menus.filter(is_default=True).update(is_default=False)
                update_fields = kwargs.get('update_fields')
                if update_fields is not None and 'is_default' not in update_fields:
                    old_is_default = type(self).objects.filter(pk=self.pk).values_list(
                        'is_default', flat=True,
                    ).first()
                    if old_is_default != self.is_default:
                        kwargs['update_fields'] = (*update_fields, 'is_default')
                super().save(*args, **kwargs)
            return
        super().save(*args, **kwargs)


@receiver(post_delete, sender=Menu)
def choose_replacement_default_menu(sender, instance, **kwargs):
    if instance.is_default:
        replacement = sender.objects.filter(restaurant_id=instance.restaurant_id).first()
        if replacement:
            sender.objects.filter(pk=replacement.pk).update(is_default=True)


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
        NEW = 'new', _('New')
        PREPARING = 'preparing', _('Preparing')
        READY = 'ready', _('Ready')
        COMPLETED = 'completed', _('Completed')
        CANCELLED = 'cancelled', _('Cancelled')

    restaurant = models.ForeignKey(
        Restaurant, on_delete=models.PROTECT, related_name='orders',
    )
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
