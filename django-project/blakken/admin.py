from django import forms
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.utils.text import slugify
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods
from adminsortable2.admin import SortableAdminMixin
import nested_admin
from nested_admin.formsets import NestedInlineFormSet

from .models import (
    ALLERGEN_CHOICES, Dish, Menu, MenuPage, NativeAppRegistration, Restaurant, RestaurantMembership,
)


class RestaurantMembershipInline(admin.TabularInline):
    model = RestaurantMembership
    extra = 0


@admin.register(NativeAppRegistration)
class NativeAppRegistrationAdmin(admin.ModelAdmin):
    list_display = ('name', 'platform', 'role', 'restaurant', 'enabled', 'id')
    list_filter = ('platform', 'role', 'enabled')
    search_fields = ('name', 'app_id', 'restaurant__name')
    readonly_fields = ('id', 'created_at')
    change_list_template = 'admin/blakken/nativeappregistration/change_list.html'

    def has_verification_status_permission(self, request):
        return self.has_view_or_change_permission(request) and (
            request.user.has_perm('blakken.view_restaurant')
            or request.user.has_perm('blakken.change_restaurant')
        )

    def get_urls(self):
        return [
            path(
                'verification-status/',
                self.admin_site.admin_view(self.verification_status),
                name='blakken_nativeappregistration_verification_status',
            ),
            *super().get_urls(),
        ]

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(request, {
            **(extra_context or {}),
            'show_verification_status': self.has_verification_status_permission(request),
        })

    @method_decorator(require_http_methods(['GET', 'POST']))
    def verification_status(self, request):
        from .verification_status import check_google_credentials, verification_status_context

        if not self.has_verification_status_permission(request):
            raise PermissionDenied
        context = verification_status_context()
        if request.method == 'POST':
            if not self.has_change_permission(request):
                raise PermissionDenied
            if request.POST.get('action') == 'check_google_credentials':
                context['google_credentials'] = check_google_credentials()
        context.update({
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': _('App verification status'),
            'can_check_credentials': self.has_change_permission(request),
            'configurations_url': reverse(
                f'{self.admin_site.name}:blakken_nativeappregistration_changelist',
            ),
        })
        return TemplateResponse(
            request, 'admin/blakken/nativeappregistration/verification_status.html', context,
        )


@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ('name', 'active', 'require_verified_orders', 'appid', 'created_at')
    list_filter = ('active', 'require_verified_orders')
    search_fields = ('name', 'appid')
    readonly_fields = ('appid', 'created_at')
    inlines = (RestaurantMembershipInline,)


@admin.register(RestaurantMembership)
class RestaurantMembershipAdmin(admin.ModelAdmin):
    list_display = ('restaurant', 'user', 'role', 'created_at')
    list_filter = ('role',)
    search_fields = ('restaurant__name', 'user__email')
    readonly_fields = ('created_at',)


class DishAdminForm(forms.ModelForm):
    allergens = forms.MultipleChoiceField(
        choices=ALLERGEN_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Dish
        fields = '__all__'


class DishInline(nested_admin.SortableHiddenMixin, nested_admin.NestedTabularInline):
    model = Dish
    form = DishAdminForm
    extra = 0
    ordering = ('position', 'pk')
    fields = ('position', 'is_visible', 'name', 'description', 'price', 'allergens')


class MenuPageAdminForm(forms.ModelForm):
    class Meta:
        model = MenuPage
        fields = '__all__'

    def clean(self):
        cleaned = super().clean()
        if 'name' in cleaned and 'slug' in cleaned:
            self.instance.name = cleaned['name']
            if cleaned.get('menu'):
                self.instance.menu = cleaned['menu']
            self.slug_base = cleaned['slug'] or slugify(cleaned['name']) or 'page'
            cleaned['slug'] = self.instance.unique_slug(base=self.slug_base)
        return cleaned


class MenuPageInlineFormSet(NestedInlineFormSet):
    def clean(self):
        reserved = set()
        for form in self.forms:
            if not form.cleaned_data or form.errors or (
                self.can_delete and self._should_delete_form(form)
            ):
                continue
            slug = form.instance.unique_slug(base=form.slug_base, reserved=reserved)
            form.instance.slug = form.cleaned_data['slug'] = slug
            reserved.add(slug)
        super().clean()


class MenuPageInline(nested_admin.SortableHiddenMixin, nested_admin.NestedStackedInline):
    model = MenuPage
    form = MenuPageAdminForm
    formset = MenuPageInlineFormSet
    extra = 0
    ordering = ('position', 'pk')
    prepopulated_fields = {'slug': ('name',)}
    fields = (
        'position', 'is_visible', 'name', 'slug', 'is_continuation', 'heading', 'decorative_title', 'descriptive_title',
        'content', 'image', 'layout', 'overlay', 'text_shadow',
    )
    inlines = (DishInline,)


@admin.register(MenuPage)
class MenuPageAdmin(SortableAdminMixin, nested_admin.NestedModelAdmin):
    form = MenuPageAdminForm
    list_display = ('name', 'decorative_title', 'heading', 'menu', 'layout', 'is_continuation', 'is_visible')
    list_filter = ('menu', 'is_visible')
    prepopulated_fields = {'slug': ('name',)}
    inlines = (DishInline,)


@admin.register(Menu)
class MenuAdmin(nested_admin.NestedModelAdmin):
    list_display = ('name', 'restaurant', 'is_default', 'show_toc')
    list_filter = ('restaurant', 'is_default')
    fields = (
        'restaurant', 'name', 'is_default', 'show_toc', 'max_per_page', 'max_per_extra_page',
        'content', 'description',
    )
    inlines = (MenuPageInline,)
