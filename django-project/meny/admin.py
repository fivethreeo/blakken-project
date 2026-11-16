from django import forms
from django.contrib import admin
from django.utils.text import slugify
from adminsortable2.admin import SortableAdminMixin
import nested_admin
from nested_admin.formsets import NestedInlineFormSet

from .models import ALLERGEN_CHOICES, Dish, Menu, MenuPage


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
    list_display = ('name', 'show_toc')
    fields = (
        'name', 'show_toc', 'max_per_page', 'max_per_extra_page', 'content', 'description',
    )
    inlines = (MenuPageInline,)
