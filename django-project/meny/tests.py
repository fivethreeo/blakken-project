import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import runpy
import signal
import tempfile
from uuid import uuid4
from threading import Thread
from urllib.error import HTTPError, URLError
from unittest.mock import Mock, patch

from celery import Celery, shared_task
from adminsortable2.admin import SortableAdminMixin
from celery.exceptions import Retry
from django.apps import apps
from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.core.cache.backends.memcached import PyMemcacheCache
from django.forms.widgets import CheckboxSelectMultiple
from django.forms.models import inlineformset_factory, modelform_factory
from django.template import TemplateSyntaxError
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import get_script_prefix, reverse, set_script_prefix
from nested_admin import SortableHiddenMixin

from .admin import (
    DishAdminForm, DishInline, MenuAdmin, MenuPageAdmin, MenuPageAdminForm,
    MenuPageInline, MenuPageInlineFormSet,
)
from .celery import app
from .models import Dish, Job, Menu, MenuPage, Order, OrderItem, ShopStatus
from .tasks import notify
from .templatetags.menu_tags import get_menu_pages


@shared_task
def runtime_test_task(value):
    return value.upper()


class MenuDataTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.menu = Menu.objects.create(name='Dinner')
        cls.front = MenuPage.objects.create(
            menu=cls.menu, name='Front', layout='cover', position=0,
        )
        cls.category = MenuPage.objects.create(
            menu=cls.menu, name='Mains', heading='Mains', position=1,
        )
        cls.continuation = MenuPage.objects.create(
            menu=cls.menu, name='More mains', is_continuation=True, position=2,
        )
        cls.drinks = MenuPage.objects.create(
            menu=cls.menu, name='Drinks', heading='Drinks', position=3,
        )
        cls.back = MenuPage.objects.create(
            menu=cls.menu, name='Back', layout='cover', position=4,
        )
        cls.later_dish = Dish.objects.create(
            menu_page=cls.category, name='Pasta', price='125.50', position=2,
            description='Fresh pasta', allergens=['gluten', 'eggs'],
        )
        cls.first_dish = Dish.objects.create(
            menu_page=cls.category, name='Soup', price=None, position=1,
        )
        cls.extra_dish = Dish.objects.create(
            menu_page=cls.continuation, name='Salad', price='0.00',
        )

    def test_public_response_groups_continuations_and_preserves_order_and_prices(self):
        with self.assertNumQueries(3):
            response = self.client.get(reverse('menu-data', args=[self.menu.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'id': self.menu.pk,
            'name': 'Dinner',
            'categories': [
                {
                    'id': self.category.pk,
                    'name': 'Mains',
                    'dishes': [
                        {
                            'id': self.first_dish.pk, 'name': 'Soup', 'description': '',
                            'price': None, 'allergens': [],
                        },
                        {
                            'id': self.later_dish.pk, 'name': 'Pasta',
                            'description': 'Fresh pasta', 'price': '125.50',
                            'allergens': ['gluten', 'eggs'],
                        },
                        {
                            'id': self.extra_dish.pk, 'name': 'Salad', 'description': '',
                            'price': '0.00', 'allergens': [],
                        },
                    ],
                },
                {'id': self.drinks.pk, 'name': 'Drinks', 'dishes': []},
            ],
        })
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_hidden_categories_continuations_dishes_and_covers_are_not_exposed(self):
        Dish.objects.create(menu_page=self.front, name='Cover dish')
        Dish.objects.create(menu_page=self.back, name='Back cover dish')
        Dish.objects.create(menu_page=self.category, name='Hidden dish', is_visible=False)
        self.continuation.is_visible = False
        self.continuation.save()
        url = reverse('menu-data', args=[self.menu.pk])
        categories = self.client.get(url).json()['categories']
        self.assertEqual(
            [dish['id'] for dish in categories[0]['dishes']],
            [self.first_dish.pk, self.later_dish.pk],
        )

        self.category.is_visible = False
        self.category.save()
        self.continuation.is_visible = True
        self.continuation.save()
        self.assertEqual(
            self.client.get(url).json()['categories'],
            [{'id': self.drinks.pk, 'name': 'Drinks', 'dishes': []}],
        )

    def test_unknown_menu_is_not_found_and_writes_are_rejected(self):
        self.assertEqual(
            self.client.get(reverse('menu-data', args=[999999])).status_code, 404,
        )
        url = reverse('menu-data', args=[self.menu.pk])
        for method in ('post', 'put', 'patch', 'delete'):
            with self.subTest(method=method):
                self.assertEqual(getattr(self.client, method)(url).status_code, 405)


class MenuAdminTests(TestCase):
    def test_menu_pages_and_dishes_are_ordered_by_position(self):
        menu = Menu.objects.create(name='Dinner', show_toc=False)
        later_page = MenuPage.objects.create(
            menu=menu, name='Mains', heading='Mains',
            decorative_title='A little joy on every plate', position=2,
        )
        first_page = MenuPage.objects.create(
            menu=menu, name='Starters', heading='Starters',
            decorative_title='Small bites, big smiles', position=1,
        )
        later_dish = Dish.objects.create(
            menu_page=first_page, name='Soup', position=2,
            allergens=['celery'],
        )
        first_dish = Dish.objects.create(
            menu_page=first_page, name='Rolls', position=1,
            allergens=['soybeans'],
        )

        self.assertEqual(list(menu.pages.all()), [first_page, later_page])
        self.assertEqual(list(first_page.dishes.all()), [first_dish, later_dish])
        self.assertFalse(menu.show_toc)

    def test_admin_nests_dishes_and_uses_allergen_checkboxes(self):
        self.assertEqual(MenuAdmin.inlines, (MenuPageInline,))
        self.assertEqual(MenuPageInline.inlines, (DishInline,))
        self.assertTrue(issubclass(MenuPageInline, SortableHiddenMixin))
        self.assertTrue(issubclass(DishInline, SortableHiddenMixin))
        self.assertIn('decorative_title', MenuPageInline.fields)
        self.assertIn('overlay', MenuPageInline.fields)
        self.assertIn('text_shadow', MenuPageInline.fields)
        self.assertIn('is_continuation', MenuPageInline.fields)
        self.assertEqual(MenuPageInline.prepopulated_fields, {'slug': ('name',)})
        self.assertEqual(MenuPageAdmin.prepopulated_fields, {'slug': ('name',)})
        form = DishAdminForm()
        self.assertIsInstance(form.fields['allergens'].widget, CheckboxSelectMultiple)
        self.assertEqual(len(form.fields['allergens'].choices), 14)

        menu = Menu.objects.create(name='Lunch')
        page = MenuPage.objects.create(
            menu=menu, name='Noodles', heading='Noodles',
            decorative_title='Good food, good mood',
        )
        form = DishAdminForm(data={
            'menu_page': page.pk,
            'position': 1,
            'name': 'Pad thai',
            'description': 'Rice noodles',
            'price': '12.50',
            'allergens': ['peanuts', 'soybeans'],
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().allergens, ['peanuts', 'soybeans'])

        user = get_user_model().objects.create_superuser(
            username='menu-admin', email='menu-admin@example.com', password='test-password',
        )
        self.client.force_login(user)
        response = self.client.get(reverse('admin:meny_menu_change', args=[menu.pk]))
        self.assertContains(response, 'type="checkbox"')
        self.assertContains(response, 'value="peanuts"')
        for field in ('content', 'description', 'max_per_page', 'max_per_extra_page'):
            self.assertContains(response, f'name="{field}"')
        for field in ('cover_content', 'back_cover_title', 'back_cover_content'):
            self.assertNotContains(response, f'name="{field}"')

    def test_page_slugs_are_generated_from_names_and_unique_per_menu(self):
        menu = Menu.objects.create(name='Lunch')
        first_page = MenuPage.objects.create(
            menu=menu, name='Curry & Rice', heading='Curry',
            decorative_title='Warm spices, happy hearts',
        )
        duplicate_page = MenuPage.objects.create(
            menu=menu, name='Curry & Rice', heading='More curry',
            decorative_title='More to enjoy',
        )
        another_menu_page = MenuPage.objects.create(
            menu=Menu.objects.create(name='Dinner'),
            name='Curry & Rice',
            heading='Curry',
            decorative_title='Made for sharing',
        )
        third_page = MenuPage.objects.create(
            menu=menu, name='Curry & Rice', slug='curry-rice',
            decorative_title='Even more to enjoy', is_continuation=True,
        )

        self.assertEqual(first_page.slug, 'curry-rice')
        self.assertEqual(duplicate_page.slug, 'curry-rice-to')
        self.assertEqual(third_page.slug, 'curry-rice-tre')
        self.assertEqual(another_menu_page.slug, 'curry-rice')

    def test_admin_resolves_colliding_continuation_slugs_in_one_inline_save(self):
        menu = Menu.objects.create(name='Lunch')
        MenuPage.objects.create(
            menu=menu, name='Curry', heading='Curry', decorative_title='Warm spices',
        )
        formset_class = inlineformset_factory(
            Menu, MenuPage, form=MenuPageAdminForm, formset=MenuPageInlineFormSet,
            fields=('position', 'name', 'slug', 'is_continuation', 'heading',
                    'decorative_title', 'layout', 'overlay'),
            extra=0,
        )
        data = {
            'pages-TOTAL_FORMS': '2', 'pages-INITIAL_FORMS': '0',
        }
        for index in range(2):
            data.update({
                f'pages-{index}-position': str(index + 1),
                f'pages-{index}-name': 'Curry',
                f'pages-{index}-slug': 'curry',
                f'pages-{index}-is_continuation': 'on',
                f'pages-{index}-heading': '',
                f'pages-{index}-decorative_title': 'Warm spices',
                f'pages-{index}-layout': 'split',
                f'pages-{index}-overlay': 'none',
            })
        formset = formset_class(data=data, instance=menu, prefix='pages')
        self.assertTrue(formset.is_valid(), (formset.errors, formset.non_form_errors()))
        pages = formset.save()
        self.assertEqual([page.slug for page in pages], ['curry-to', 'curry-tre'])
        self.assertTrue(all(page.is_continuation and not page.heading for page in pages))

    def test_only_continuation_pages_can_omit_category_headings(self):
        menu = Menu.objects.create(name='Lunch')
        data = {
            'menu': menu.pk, 'position': 1, 'name': 'Curry',
            'slug': 'curry', 'heading': '', 'decorative_title': 'Warm spices',
            'layout': 'split', 'overlay': 'none',
        }
        form = MenuPageAdminForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('heading', form.errors)
        form = MenuPageAdminForm(data={**data, 'is_continuation': True})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().slug, 'curry')
        form = MenuPageAdminForm(data={**data, 'is_continuation': True, 'layout': 'cover'})
        self.assertFalse(form.is_valid())
        self.assertIn('is_continuation', form.errors)

    def test_pages_have_sortable_admin_with_menu_filter_and_dish_inline(self):
        self.assertTrue(issubclass(MenuPageAdmin, SortableAdminMixin))
        self.assertEqual(MenuPageAdmin.list_filter, ('menu', 'is_visible'))
        self.assertEqual(MenuPageAdmin.inlines, (DishInline,))
        self.assertIsInstance(admin.site._registry[MenuPage], MenuPageAdmin)

        menu = Menu.objects.create(name='Lunch')
        page = MenuPage.objects.create(
            menu=menu, name='Noodles', heading='Noodles',
            decorative_title='Good food, good mood',
        )
        MenuPage.objects.create(
            menu=Menu.objects.create(name='Dinner'), name='Curry', heading='Curry',
            decorative_title='Warm spices, happy hearts',
        )
        user = get_user_model().objects.create_superuser(
            username='page-admin', email='page-admin@example.com', password='test-password',
        )
        self.client.force_login(user)
        response = self.client.get(reverse('admin:meny_menupage_changelist'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['cl'].filter_specs), 2)
        self.assertContains(response, 'adminsortable2')
        change_response = self.client.get(reverse('admin:meny_menupage_change', args=[page.pk]))
        self.assertEqual(change_response.status_code, 200)
        self.assertContains(change_response, 'name="overlay"')
        self.assertContains(change_response, 'name="text_shadow"')
        self.assertContains(change_response, 'name="is_continuation"')


@override_settings(FRONTEND_ENABLED=False)
class DishEditTests(TestCase):
    def setUp(self):
        self.menu = Menu.objects.create(id=2, name='Lunch')
        self.page = MenuPage.objects.create(
            menu=self.menu, name='Curry', heading='Curry', decorative_title='Warm spices',
        )
        self.dish = Dish.objects.create(
            menu_page=self.page, name='Butter chicken', description='A mild curry.',
            price='249.00', allergens=['milk'], position=7,
        )
        self.staff = get_user_model().objects.create_user(username='editor', is_staff=True)
        self.url = reverse('dish-detail', args=[self.menu.pk, self.dish.pk])

    def test_staff_and_superusers_can_fetch_and_update_dish_fields(self):
        superuser = get_user_model().objects.create_user(
            username='super-editor', is_superuser=True, is_staff=False,
        )
        for user in (self.staff, superuser):
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.get(self.url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['dish']['name'], self.dish.name)
                self.assertEqual(response.json()['dish']['price'], str(self.dish.price))
                self.assertIn(['milk', 'Melk'], response.json()['allergen_choices'])
                response = self.client.patch(self.url, {
                    'name': '  Korma  ', 'description': 'Cream and cashews.',
                    'price': '259.50', 'allergens': ['milk', 'nuts'],
                }, content_type='application/json')
                self.assertEqual(response.status_code, 200)
                self.dish.refresh_from_db()
                self.assertEqual(self.dish.name, 'Korma')
                self.assertEqual(self.dish.description, 'Cream and cashews.')
                self.assertEqual(str(self.dish.price), '259.50')
                self.assertEqual(self.dish.allergens, ['milk', 'nuts'])
                self.assertEqual(self.dish.position, 7)
                self.assertEqual(self.dish.menu_page_id, self.page.pk)

    def test_partial_updates_accept_zero_price_and_clear_optional_fields(self):
        self.client.force_login(self.staff)
        response = self.client.patch(self.url, {'price': 0}, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['dish']['price'], '0.00')
        self.assertContains(
            self.client.get(reverse('menu-pages', args=[self.menu.pk])),
            '<p class="menu-price">0 kr</p>', html=True,
        )
        response = self.client.patch(self.url, {
            'price': None, 'description': '', 'allergens': [],
        }, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.dish.refresh_from_db()
        self.assertEqual(self.dish.name, 'Butter chicken')
        self.assertIsNone(self.dish.price)
        self.assertEqual(self.dish.description, '')
        self.assertEqual(self.dish.allergens, [])

    def test_visibility_updates_preserve_dish_data_and_require_a_boolean(self):
        self.client.force_login(self.staff)
        for visible in (False, True):
            response = self.client.patch(self.url, {'is_visible': visible}, content_type='application/json')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['dish']['is_visible'], visible)
            self.dish.refresh_from_db()
            self.assertEqual(self.dish.is_visible, visible)
            self.assertEqual(self.dish.name, 'Butter chicken')
            self.assertEqual(self.dish.position, 7)
            self.assertEqual(str(self.dish.price), '249.00')
        for value in ('false', 0, 1, None, [], {}):
            response = self.client.patch(
                self.url, {'name': 'Do not save', 'is_visible': value}, content_type='application/json',
            )
            self.assertEqual(response.status_code, 400)
            self.assertIn('is_visible', response.json()['errors'])
        self.dish.refresh_from_db()
        self.assertTrue(self.dish.is_visible)
        self.assertEqual(self.dish.name, 'Butter chicken')

    def test_invalid_values_do_not_save_any_fields(self):
        self.client.force_login(self.staff)
        before = Dish.objects.values().get(pk=self.dish.pk)
        for invalid in (
            {'name': ' '}, {'name': 'a' * 151}, {'name': 7}, {'description': None},
            {'price': '-0.01'}, {'price': True}, {'price': {}}, {'price': 'NaN'},
            {'price': '9999999.99'}, {'price': '1.001'},
            {'allergens': 'milk'}, {'allergens': ['unknown']}, {'allergens': [1]},
        ):
            with self.subTest(invalid=invalid):
                response = self.client.patch(
                    self.url, {'name': 'Do not save', **invalid}, content_type='application/json',
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn('errors', response.json())
                self.assertEqual(Dish.objects.values().get(pk=self.dish.pk), before)

    def test_invalid_json_and_uneditable_fields_are_rejected(self):
        self.client.force_login(self.staff)
        for body in ('{', '[]', 'null', '{"position": 0}', '{"menu_page": 999}'):
            with self.subTest(body=body):
                response = self.client.patch(self.url, body, content_type='application/json')
                self.assertEqual(response.status_code, 400)
        self.assertEqual(
            self.client.patch(self.url, '{}', content_type='text/plain').status_code, 415,
        )
        self.assertEqual(self.client.post(self.url).status_code, 405)
        self.assertEqual(self.client.put(self.url).status_code, 405)
        self.dish.refresh_from_db()
        self.assertEqual(self.dish.position, 7)
        self.assertEqual(self.dish.menu_page_id, self.page.pk)

    def test_dish_reads_and_updates_are_scoped_to_the_requested_menu(self):
        self.client.force_login(self.staff)
        other = Menu.objects.create(name='Other menu')
        for menu_id, dish_id in ((other.pk, self.dish.pk), (self.menu.pk, self.dish.pk + 1000)):
            url = reverse('dish-detail', args=[menu_id, dish_id])
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(
                self.client.patch(url, {'name': 'Changed'}, content_type='application/json').status_code,
                404,
            )
        self.dish.refresh_from_db()
        self.assertEqual(self.dish.name, 'Butter chicken')

    def test_anonymous_and_ordinary_users_cannot_read_or_edit(self):
        ordinary_user = get_user_model().objects.create_user(username='reader')
        for user, status in ((None, 401), (ordinary_user, 403)):
            if user:
                self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, status)
            self.assertEqual(self.client.delete(self.url).status_code, status)
            self.assertEqual(
                self.client.get(reverse('dish-list', args=[self.menu.pk, self.page.pk])).status_code,
                status,
            )
            self.assertEqual(
                self.client.post(
                    reverse('dish-list', args=[self.menu.pk, self.page.pk]),
                    {'name': 'New dish'}, content_type='application/json',
                ).status_code,
                status,
            )
            self.assertEqual(
                self.client.patch(
                    self.url, {'name': 'Changed'}, content_type='application/json',
                ).status_code,
                status,
            )
        self.dish.refresh_from_db()
        self.assertEqual(self.dish.name, 'Butter chicken')

    def test_updates_require_the_menu_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        token = str(client.get('/').context['csrf_token'])
        self.assertEqual(
            client.patch(self.url, {'name': 'Changed'}, content_type='application/json').status_code,
            403,
        )
        response = client.patch(
            self.url, {'name': 'Changed'}, content_type='application/json', HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 200)
        self.dish.refresh_from_db()
        self.assertEqual(self.dish.name, 'Changed')
        create_url = reverse('dish-list', args=[self.menu.pk, self.page.pk])
        self.assertEqual(
            client.post(create_url, {'name': 'New dish'}, content_type='application/json').status_code,
            403,
        )
        self.assertEqual(client.delete(self.url).status_code, 403)
        response = client.post(
            create_url, {'name': 'New dish'}, content_type='application/json', HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(client.delete(response['Location'], HTTP_X_CSRFTOKEN=token).status_code, 204)

    def test_staff_and_superusers_create_at_the_end_of_the_same_category(self):
        create_url = reverse('dish-list', args=[self.menu.pk, self.page.pk])
        superuser = get_user_model().objects.create_user(
            username='creator-superuser', is_superuser=True, is_staff=False,
        )
        for index, user in enumerate((self.staff, superuser)):
            self.client.force_login(user)
            response = self.client.post(create_url, {
                'name': f'New dish {index}', 'description': 'Freshly prepared.',
                'price': '199.50', 'allergens': ['milk'],
            }, content_type='application/json')
            self.assertEqual(response.status_code, 201)
            created = Dish.objects.get(pk=response.json()['dish']['id'])
            self.assertEqual(created.menu_page_id, self.page.pk)
            self.assertEqual(created.position, 8 + index)
            self.assertEqual(created.allergens, ['milk'])
            self.assertEqual(str(created.price), '199.50')
            self.assertEqual(response['Location'], reverse('dish-detail', args=[self.menu.pk, created.pk]))
            self.assertEqual(response.json()['create_url'], create_url)
            self.assertEqual(response.json()['category_slug'], self.page.slug)

    def test_creation_validates_fields_and_category_scope(self):
        self.client.force_login(self.staff)
        url = reverse('dish-list', args=[self.menu.pk, self.page.pk])
        for data in ({}, {'name': ''}, {'name': 'New dish', 'price': '-1'}, {'position': 1}):
            self.assertEqual(self.client.post(url, data, content_type='application/json').status_code, 400)
        other = Menu.objects.create(name='Other menu')
        wrong_menu = reverse('dish-list', args=[other.pk, self.page.pk])
        self.assertEqual(
            self.client.post(wrong_menu, {'name': 'Wrong menu'}, content_type='application/json').status_code,
            404,
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['dish'], {
            'id': None, 'name': '', 'description': '', 'price': None, 'allergens': [], 'is_visible': True,
        })
        self.assertEqual(response.json()['create_url'], url)
        self.assertTrue(response.json()['allergen_choices'])
        self.assertEqual(self.page.dishes.count(), 1)

    def test_deletion_is_menu_scoped_and_leaves_other_dishes_and_category_intact(self):
        self.client.force_login(self.staff)
        other_dish = Dish.objects.create(menu_page=self.page, name='Keep me', position=8)
        other_menu = Menu.objects.create(name='Other menu')
        wrong_menu = reverse('dish-detail', args=[other_menu.pk, self.dish.pk])
        self.assertEqual(self.client.delete(wrong_menu).status_code, 404)
        response = self.client.delete(self.url)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(Dish.objects.filter(pk=self.dish.pk).exists())
        self.assertEqual(list(self.page.dishes.all()), [other_dish])
        self.assertTrue(MenuPage.objects.filter(pk=self.page.pk).exists())
        self.assertEqual(self.client.get(self.url).status_code, 404)
        superuser = get_user_model().objects.create_user(
            username='deleting-superuser', is_superuser=True, is_staff=False,
        )
        self.client.force_login(superuser)
        self.assertEqual(
            self.client.delete(reverse('dish-detail', args=[self.menu.pk, other_dish.pk])).status_code,
            204,
        )
        self.assertEqual(self.page.dishes.count(), 0)
        self.assertTrue(MenuPage.objects.filter(pk=self.page.pk).exists())


@override_settings(FRONTEND_ENABLED=False)
class MenuPageActionTests(TestCase):
    def setUp(self):
        self.menu = Menu.objects.create(id=2, name='Lunch', show_toc=False, max_per_page=2, max_per_extra_page=2)
        self.front = MenuPage.objects.create(
            menu=self.menu, name='Front', heading='Lunch', decorative_title='Welcome',
            layout='cover', position=0,
        )
        self.category = MenuPage.objects.create(
            menu=self.menu, name='Curry', heading='Curry', decorative_title='Warm spices', position=3,
        )
        self.continuation = MenuPage.objects.create(
            menu=self.menu, name='Curry', slug='curry-manual', is_continuation=True,
            decorative_title='More warm spices', position=3,
        )
        self.next_category = MenuPage.objects.create(
            menu=self.menu, name='Dessert', heading='Dessert', decorative_title='A sweet ending', position=3,
        )
        self.back = MenuPage.objects.create(
            menu=self.menu, name='Back', heading='Thanks', decorative_title='See you soon',
            layout='cover', position=10,
        )
        for index in range(3):
            Dish.objects.create(menu_page=self.category, name=f'Curry dish {index}', position=index)
        self.staff = get_user_model().objects.create_user(username='page-editor', is_staff=True)
        self.url = reverse('menu-pages', args=[self.menu.pk])
        self.move_url = reverse('move-page', args=[self.menu.pk, self.category.pk])
        self.data = {
            'after_page_id': self.category.pk,
            'name': 'Lunch specials', 'heading': 'Something special',
            'decorative_title': 'Made with care', 'content': 'Seasonal favourites.',
        }

    def test_visibility_round_trip_hides_category_and_all_continuations_only_for_customers(self):
        self.client.force_login(self.staff)
        url = reverse('page-visibility', args=[self.menu.pk, self.category.pk])
        manual_dish = Dish.objects.create(menu_page=self.continuation, name='Manual curry')
        for visible in (False, True):
            response = self.client.patch(url, {'is_visible': visible}, content_type='application/json')
            self.assertEqual(response.status_code, 200)
            for page in (self.category, self.continuation):
                page.refresh_from_db()
                self.assertEqual(page.is_visible, visible)
            self.assertEqual(Dish.objects.filter(menu_page=self.category).count(), 3)
            manual_dish.refresh_from_db()
            self.assertTrue(manual_dish.is_visible)
            staff_view = self.client.get(self.url)
            self.assertContains(staff_view, 'Curry dish 0')
            self.assertContains(staff_view, 'Manual curry')
            self.assertContains(staff_view, 'id="curry-to"')
            self.assertContains(staff_view, f'aria-label="{"Skjul" if visible else "Vis"} Curry for kunder"')
            icon = 'eyeopen' if visible else 'eyedisabled'
            self.assertContains(staff_view, f'<use href="#{icon}" xlink:href="#{icon}"></use>')
            if not visible:
                self.assertContains(staff_view, '(skjult for kunder)')
            guest = Client().get(self.url)
            for text in ('Curry dish 0', 'Manual curry', 'id="curry-to"'):
                if visible:
                    self.assertContains(guest, text)
                else:
                    self.assertNotContains(guest, text)
            self.assertContains(guest, 'Dessert')
            self.assertContains(guest, 'Welcome')
            self.assertContains(guest, 'See you soon')
        self.assertEqual(list(self.menu.pages.values_list('pk', flat=True)), [
            self.front.pk, self.category.pk, self.continuation.pk, self.next_category.pk, self.back.pk,
        ])

    def test_page_visibility_requires_staff_csrf_scope_and_strict_boolean_and_protects_covers(self):
        url = reverse('page-visibility', args=[self.menu.pk, self.category.pk])
        data = {'is_visible': False}
        self.assertEqual(self.client.patch(url, data, content_type='application/json').status_code, 401)
        ordinary = get_user_model().objects.create_user(username='visibility-reader')
        self.client.force_login(ordinary)
        self.assertEqual(self.client.patch(url, data, content_type='application/json').status_code, 403)
        superuser = get_user_model().objects.create_user(
            username='visibility-superuser', is_superuser=True, is_staff=False,
        )
        for user in (self.staff, superuser):
            self.client.force_login(user)
            for visible in (False, True):
                self.assertEqual(self.client.patch(
                    url, {'is_visible': visible}, content_type='application/json',
                ).status_code, 200)
        self.assertEqual(self.client.get(url).status_code, 405)
        for body in ('{', 'null', '[]', '{}', '{"is_visible":false,"name":"Other"}',
                     '{"is_visible":0}', '{"is_visible":"false"}'):
            self.assertEqual(self.client.patch(url, body, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.patch(url, '{}', content_type='text/plain').status_code, 415)
        other = Menu.objects.create(name='Other')
        for menu_id, page_id, expected in (
            (other.pk, self.category.pk, 404), (self.menu.pk, self.back.pk + 100, 404),
            (self.menu.pk, self.front.pk, 400), (self.menu.pk, self.back.pk, 400),
        ):
            target = reverse('page-visibility', args=[menu_id, page_id])
            self.assertEqual(self.client.patch(target, data, content_type='application/json').status_code, expected)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        token = str(client.get('/').context['csrf_token'])
        self.assertEqual(client.patch(url, data, content_type='application/json').status_code, 403)
        self.assertEqual(client.patch(
            url, data, content_type='application/json', HTTP_X_CSRFTOKEN=token,
        ).status_code, 200)

    def test_moves_preserve_covers_and_manual_and_automatic_continuations(self):
        superuser = get_user_model().objects.create_user(username='page-superuser', is_superuser=True)
        for user in (self.staff, superuser):
            self.client.force_login(user)
            response = self.client.post(self.move_url, {'direction': 'right'})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['moved'])
            self.assertEqual(list(self.menu.pages.all()), [
                self.front, self.next_category, self.category, self.continuation, self.back,
            ])
            rendered = get_menu_pages(self.menu)
            self.assertEqual([page.slug for page in rendered], [
                'front', 'dessert', 'curry', 'curry-to', 'curry-manual', 'back',
            ])
            url = reverse('move-page', args=[self.menu.pk, self.continuation.pk])
            self.assertTrue(self.client.post(url, {'direction': 'left'}).json()['moved'])
            self.assertEqual(list(self.menu.pages.values_list('position', flat=True)), list(range(5)))
            self.assertEqual(list(self.menu.pages.all()), [
                self.front, self.category, self.continuation, self.next_category, self.back,
            ])

    def test_move_boundaries_and_covers_are_not_reordered(self):
        self.client.force_login(self.staff)
        for page, direction in (
            (self.front, 'right'), (self.back, 'left'),
            (self.category, 'left'), (self.next_category, 'right'),
        ):
            url = reverse('move-page', args=[self.menu.pk, page.pk])
            self.assertFalse(self.client.post(url, {'direction': direction}).json()['moved'])
        self.assertEqual(self.client.post(self.move_url, {'direction': 'up'}).status_code, 400)
        self.assertEqual(self.client.get(self.move_url).status_code, 405)
        self.assertEqual(list(self.menu.pages.all()), [
            self.front, self.category, self.continuation, self.next_category, self.back,
        ])

    def test_new_category_is_inserted_after_all_continuations_without_copying_dishes(self):
        self.client.force_login(self.staff)
        response = self.client.post(self.url, self.data, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        page = MenuPage.objects.get(pk=response.json()['page']['id'])
        self.assertEqual(page.heading, self.data['heading'])
        self.assertEqual(page.content, self.data['content'])
        self.assertEqual(page.layout, 'split')
        self.assertEqual(page.dishes.count(), 0)
        self.assertEqual(list(self.menu.pages.all()), [
            self.front, self.category, self.continuation, page, self.next_category, self.back,
        ])
        blank = self.client.get(reverse('dish-list', args=[self.menu.pk, page.pk])).json()
        self.assertEqual(blank['dish']['name'], '')
        self.assertEqual(blank['category_slug'], page.slug)

    def test_creation_accepts_front_cover_and_avoids_slug_collisions(self):
        self.client.force_login(self.staff)
        response = self.client.post(self.url, {
            **self.data, 'name': 'Curry', 'after_page_id': self.front.pk,
        }, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['page']['slug'], 'curry-to')
        self.assertEqual(self.menu.pages.all()[1].pk, response.json()['page']['id'])
        slugs = [page.slug for page in get_menu_pages(self.menu)]
        self.assertEqual(len(slugs), len(set(slugs)))

    def test_creation_works_for_an_empty_book(self):
        self.menu.pages.exclude(pk__in=[self.front.pk, self.back.pk]).delete()
        superuser = get_user_model().objects.create_user(username='empty-book-editor', is_superuser=True)
        self.client.force_login(superuser)
        response = self.client.post(self.url, {
            **self.data, 'after_page_id': self.front.pk,
        }, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.menu.pages.count(), 3)
        self.assertEqual(self.menu.pages.first(), self.front)
        self.assertEqual(self.menu.pages.last(), self.back)

    def test_delete_removes_category_continuations_and_dishes_but_keeps_neighbors(self):
        self.client.force_login(self.staff)
        Dish.objects.create(menu_page=self.continuation, name='Manual continuation dish')
        preserved = Dish.objects.create(menu_page=self.next_category, name='Keep this dessert')
        response = self.client.delete(reverse('delete-page', args=[self.menu.pk, self.continuation.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['category_slug'], self.next_category.slug)
        self.assertEqual(list(self.menu.pages.all()), [self.front, self.next_category, self.back])
        self.assertEqual(list(self.menu.pages.values_list('position', flat=True)), [0, 1, 2])
        self.assertEqual(list(Dish.objects.filter(menu_page__menu=self.menu)), [preserved])
        self.assertFalse(any(page.slug.startswith('curry') for page in get_menu_pages(self.menu)))

    def test_delete_protects_covers_and_menu_scope_and_keeps_an_empty_book_addable(self):
        superuser = get_user_model().objects.create_user(username='deleting-page-superuser', is_superuser=True)
        self.client.force_login(superuser)
        for cover in (self.front, self.back):
            self.assertEqual(
                self.client.delete(reverse('delete-page', args=[self.menu.pk, cover.pk])).status_code, 400,
            )
        other = Menu.objects.create(name='Other menu')
        self.assertEqual(
            self.client.delete(reverse('delete-page', args=[other.pk, self.category.pk])).status_code, 404,
        )
        self.assertEqual(
            self.client.get(reverse('delete-page', args=[self.menu.pk, self.category.pk])).status_code, 405,
        )
        self.assertEqual(
            self.client.delete(reverse('delete-page', args=[self.menu.pk, self.category.pk])).status_code, 200,
        )
        response = self.client.delete(reverse('delete-page', args=[self.menu.pk, self.next_category.pk]))
        self.assertEqual(response.json()['category_slug'], self.front.slug)
        self.assertEqual(list(self.menu.pages.all()), [self.front, self.back])
        response = self.client.get('/')
        self.assertContains(response, 'data-page-action="add"', count=1)
        self.assertNotContains(response, 'data-page-action="delete"')

    def test_invalid_creation_and_wrong_menu_do_not_change_any_pages(self):
        self.client.force_login(self.staff)
        for data in (
            {}, [], {**self.data, 'name': True}, {**self.data, 'heading': ''},
            {**self.data, 'layout': 'cover'}, {**self.data, 'after_page_id': True},
            {**self.data, 'after_page_id': self.back.pk},
        ):
            self.assertEqual(self.client.post(self.url, data, content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(self.url, 'invalid', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(self.url, self.data).status_code, 415)
        other = Menu.objects.create(name='Other menu')
        self.assertEqual(
            self.client.post(reverse('menu-pages', args=[other.pk]), self.data, content_type='application/json').status_code,
            404,
        )
        self.assertEqual(
            self.client.post(reverse('move-page', args=[other.pk, self.category.pk]), {'direction': 'right'}).status_code,
            404,
        )
        self.assertEqual(self.menu.pages.count(), 5)

    def test_page_actions_require_staff_and_csrf(self):
        ordinary = get_user_model().objects.create_user(username='page-reader')
        for user, status in ((None, 401), (ordinary, 403)):
            if user:
                self.client.force_login(user)
            self.assertEqual(self.client.post(self.url, self.data, content_type='application/json').status_code, status)
            self.assertEqual(self.client.post(self.move_url, {'direction': 'right'}).status_code, status)
            self.assertEqual(
                self.client.delete(reverse('delete-page', args=[self.menu.pk, self.category.pk])).status_code,
                status,
            )
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        token = str(client.get('/').context['csrf_token'])
        self.assertEqual(client.post(self.url, self.data, content_type='application/json').status_code, 403)
        self.assertEqual(client.post(self.move_url, {'direction': 'right'}).status_code, 403)
        self.assertEqual(client.post(
            self.url, self.data, content_type='application/json', HTTP_X_CSRFTOKEN=token,
        ).status_code, 201)
        self.assertEqual(client.post(
            self.move_url, {'direction': 'right'}, HTTP_X_CSRFTOKEN=token,
        ).status_code, 200)
        delete_url = reverse('delete-page', args=[self.menu.pk, self.category.pk])
        self.assertEqual(client.delete(delete_url).status_code, 403)
        self.assertEqual(client.delete(delete_url, HTTP_X_CSRFTOKEN=token).status_code, 200)

    def test_staff_controls_use_category_boundaries_and_dish_plus_is_beside_heading(self):
        for user in (None, get_user_model().objects.create_user(username='ordinary-page-reader'), self.staff):
            if user:
                self.client.force_login(user)
            response = self.client.get('/')
            self.assertNotContains(response, 'data-dish-add')
            if user == self.staff:
                self.assertContains(response, 'data-page-action="right"', count=3)
                self.assertContains(response, 'data-page-action="left"', count=1)
                self.assertContains(response, 'data-page-action="add"', count=5)
                self.assertContains(response, 'data-page-action="delete"', count=4)
                self.assertContains(response, '<use href="#cross" xlink:href="#cross">', count=4)
                self.assertContains(response, 'data-dish-action="add"', count=2)
                self.assertContains(response, 'title="Flytt Curry til høyre"', count=3)
                self.assertContains(response, 'title="Legg til rett i Dessert"', count=1)
                self.assertContains(response, f'data-create-url="{reverse("dish-list", args=[self.menu.pk, self.next_category.pk])}"')
            else:
                self.assertNotContains(response, 'data-page-action')
                self.assertNotContains(response, 'data-dish-action="add"')


@override_settings(FRONTEND_ENABLED=False)
class DishMoveTests(TestCase):
    def setUp(self):
        self.menu = Menu.objects.create(id=2, name='Lunch', show_toc=False)
        MenuPage.objects.create(
            menu=self.menu, name='Front', heading='Lunch', decorative_title='Welcome',
            layout='cover', position=0,
        )
        self.page = MenuPage.objects.create(
            menu=self.menu, name='Curry', heading='Curry', decorative_title='Warm spices',
            position=1,
        )
        MenuPage.objects.create(
            menu=self.menu, name='Back', heading='Thanks', decorative_title='See you soon',
            layout='cover', position=2,
        )
        self.dishes = [
            Dish.objects.create(menu_page=self.page, name=f'Dish {index}', position=index)
            for index in range(9)
        ]
        self.staff = get_user_model().objects.create_user(username='dish-editor', is_staff=True)
        self.url = reverse('move-dish', args=[self.menu.pk, self.dishes[4].pk])

    def test_staff_and_superusers_can_move_across_the_automatic_page_boundary(self):
        superuser = get_user_model().objects.create_user(
            username='dish-superuser', is_superuser=True, is_staff=False,
        )
        for user in (self.staff, superuser):
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.post(self.url, {'direction': 'up'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {'moved': True})
                expected = self.dishes.copy()
                expected[3], expected[4] = expected[4], expected[3]
                self.assertEqual(list(self.page.dishes.all()), expected)
                pages = get_menu_pages(self.menu)[1:-1]
                self.assertEqual(pages[0].turnpage_dishes[-1].pk, self.dishes[4].pk)
                self.assertEqual(pages[1].turnpage_dishes[0].pk, self.dishes[3].pk)
                self.assertEqual([page.slug for page in pages], ['curry', 'curry-to'])
                self.assertEqual(
                    self.client.post(self.url, {'direction': 'down'}).json(), {'moved': True},
                )
                self.assertEqual(list(self.page.dishes.all()), self.dishes)

    def test_boundary_moves_are_noops(self):
        self.client.force_login(self.staff)
        before = list(self.page.dishes.values_list('pk', 'position'))
        for dish, direction in ((self.dishes[0], 'up'), (self.dishes[-1], 'down')):
            url = reverse('move-dish', args=[self.menu.pk, dish.pk])
            response = self.client.post(url, {'direction': direction})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {'moved': False})
        self.assertEqual(list(self.page.dishes.values_list('pk', 'position')), before)

    def test_duplicate_positions_are_normalized_so_moves_still_work(self):
        self.page.dishes.update(position=0)
        self.client.force_login(self.staff)
        response = self.client.post(self.url, {'direction': 'up'})
        self.assertEqual(response.status_code, 200)
        expected = self.dishes.copy()
        expected[3], expected[4] = expected[4], expected[3]
        self.assertEqual(list(self.page.dishes.all()), expected)
        self.assertEqual(list(self.page.dishes.values_list('position', flat=True)), list(range(9)))

    def test_anonymous_and_ordinary_users_cannot_move_dishes(self):
        self.assertEqual(self.client.post(self.url, {'direction': 'up'}).status_code, 401)
        self.client.force_login(get_user_model().objects.create_user(username='dish-reader'))
        self.assertEqual(self.client.post(self.url, {'direction': 'up'}).status_code, 403)
        self.assertEqual(list(self.page.dishes.all()), self.dishes)

    def test_moves_require_post_valid_direction_and_a_dish_in_the_requested_menu(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url).status_code, 405)
        for data in ({}, {'direction': 'sideways'}):
            self.assertEqual(self.client.post(self.url, data).status_code, 400)
        other_page = MenuPage.objects.create(
            menu=Menu.objects.create(name='Dinner'), name='Other', heading='Other',
            decorative_title='Another menu',
        )
        other_dish = Dish.objects.create(menu_page=other_page, name='Other dish')
        for menu_id, dish_id in (
            (self.menu.pk, other_dish.pk),
            (other_page.menu_id, self.dishes[4].pk),
            (self.menu.pk, other_dish.pk + 1000),
        ):
            url = reverse('move-dish', args=[menu_id, dish_id])
            self.assertEqual(self.client.post(url, {'direction': 'up'}).status_code, 404)
        self.assertEqual(list(self.page.dishes.all()), self.dishes)
        other_dish.refresh_from_db()
        self.assertEqual(other_dish.position, 0)

    def test_moves_require_a_csrf_token_issued_by_the_menu(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        response = client.get('/')
        token = str(response.context['csrf_token'])
        self.assertContains(response, f'data-csrf-token="{token}"')
        self.assertIn(settings.CSRF_COOKIE_NAME, response.cookies)
        self.assertEqual(client.post(self.url, {'direction': 'up'}).status_code, 403)
        self.assertEqual(list(self.page.dishes.all()), self.dishes)
        response = client.post(self.url, {'direction': 'up'}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'moved': True})


class OptionalFrontendTests(TestCase):
    def setUp(self):
        Menu.objects.create(id=2, name='Test menu')

    @override_settings(FRONTEND_ENABLED=False, RSBUILD_MANIFEST='/missing/manifest.json')
    def test_django_page_renders_without_reading_a_disabled_frontend_manifest(self):
        with patch('meny.templatetags.rsbuild._load_manifest') as load_manifest:
            response = self.client.get('/')
        self.assertContains(response, '<title>Test menu</title>', html=True)
        self.assertNotContains(response, 'class="menu-heading')
        self.assertContains(response, "classList.replace('no-js', 'with-js')")
        self.assertNotContains(response, '<script defer')
        self.assertNotContains(response, 'rel="stylesheet"')
        self.assertTemplateUsed(response, 'includes/icons.svg')
        self.assertContains(
            response,
            '<svg xmlns="http://www.w3.org/2000/svg" style="display: none" '
            'aria-hidden="true" focusable="false">',
        )
        load_manifest.assert_not_called()

    @override_settings(FRONTEND_ENABLED=True, RSBUILD_MANIFEST='/missing/manifest.json')
    def test_enabled_frontend_still_requires_a_built_manifest(self):
        with self.assertRaisesMessage(TemplateSyntaxError, 'dev server or build first'):
            self.client.get('/')

    def test_enabled_frontend_still_emits_production_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'manifest.json'
            manifest.write_text(json.dumps({'entries': {'index': {'initial': {
                'js': ['/js/index.js'], 'css': ['/css/index.css'],
            }}}}))
            with override_settings(
                FRONTEND_ENABLED=True, RSBUILD_MANIFEST=manifest,
                RSBUILD_BASE_URL='/meny/static/',
            ):
                response = self.client.get('/')
        self.assertContains(response, '<script defer src="/meny/static/js/index.js"></script>', html=True)
        self.assertContains(response, '<link rel="stylesheet" href="/meny/static/css/index.css">', html=True)


class MenuRenderingTests(TestCase):
    def test_manual_continuations_keep_feelgood_heading_and_dishes_without_category_copy(self):
        menu = Menu.objects.create(name='Lunch', show_toc=True)
        MenuPage.objects.create(
            menu=menu, name='Front', heading='Lunch', decorative_title='Welcome',
            layout='cover', position=0,
        )
        category = MenuPage.objects.create(
            menu=menu, name='Curry', heading='Curry', decorative_title='Warm spices', position=1,
        )
        continuation = MenuPage.objects.create(
            menu=menu, name='Curry', is_continuation=True, decorative_title='Warm spices',
            descriptive_title='Do not repeat this title', content='Do not repeat this copy',
            position=2,
        )
        MenuPage.objects.create(
            menu=menu, name='Back', heading='Thanks', decorative_title='See you soon',
            layout='cover', position=3,
        )
        for index in range(6):
            Dish.objects.create(
                menu_page=category if index < 4 else continuation,
                name=f'Curry dish {index + 1}', position=index,
            )
        response = self.client.get(reverse('menu-pages', args=[menu.pk]))
        self.assertContains(response, '<p class="slide-label">Warm spices</p>', count=2, html=True)
        self.assertContains(response, '<h2 id="curry">Curry</h2>', count=1, html=True)
        self.assertContains(response, 'data-continuation data-toc-exclude id="curry-to"')
        self.assertContains(response, 'aria-label="Curry (fortsettelse)"')
        self.assertNotContains(response, '<h2 id="curry-to"')
        self.assertNotContains(response, 'Do not repeat')
        self.assertContains(response, '<span data-page-number>03</span>', html=True)
        for index in range(6):
            self.assertContains(response, f'Curry dish {index + 1}')

    def test_cart_icon_buttons_identify_each_dish_including_unpriced_dishes(self):
        menu = Menu.objects.create(name='Lunch')
        page = MenuPage.objects.create(
            menu=menu, name='Starters', heading='Starters', decorative_title='Lunch',
        )
        dishes = [
            Dish.objects.create(menu_page=page, name='Soup', price='99.00'),
            Dish.objects.create(menu_page=page, name='Daily special'),
        ]
        response = self.client.get(reverse('menu-pages', args=[menu.pk]))
        for dish in dishes:
            for action, label in [('add', f'Legg til {dish.name} i handlekurven')]:
                disabled = 'disabled ' if dish.price is None else ''
                price = dish.price if dish.price is not None else 'None'
                self.assertContains(
                    response,
                    '<button class="cart-button cluster align-items:center justify-content:center" '
                    f'type="button" data-cart-action="{action}" data-dish-id="{dish.pk}" '
                    f'data-dish-name="{dish.name}" data-dish-price="{price}" {disabled}'
                    f'aria-label="{label}" title="{label}"><svg class="icon" aria-hidden="true" focusable="false">'
                    f'<use href="#cart{action}" xlink:href="#cart{action}"></use></svg></button>',
                    html=True,
                )
        self.assertContains(response, '<p class="menu-price">99 kr</p>', html=True)
        self.assertNotContains(response, 'data-cart-action="remove"')

    @override_settings(FRONTEND_ENABLED=False)
    def test_fragment_uses_the_same_pages_template_and_reflects_saved_changes(self):
        menu = Menu.objects.create(id=2, name='Lunch', show_toc=False)
        page = MenuPage.objects.create(
            menu=menu, name='Front', heading='Welcome', decorative_title='Lunch',
        )
        dish = Dish.objects.create(menu_page=page, name='Soup', price='99.00')
        url = reverse('menu-pages', args=[menu.pk])
        initial = self.client.get('/')
        fragment = self.client.get(url)
        self.assertTemplateUsed(initial, 'menu/pages.html')
        self.assertTemplateUsed(fragment, 'menu/pages.html')
        self.assertContains(initial, f'data-pages-url="{url}"')
        self.assertContains(fragment, f'data-menu-page="{page.pk}"')
        self.assertContains(fragment, 'Soup')
        self.assertNotContains(fragment, '<html')
        self.assertNotContains(fragment, 'data-book-canvas')
        self.assertNotContains(fragment, '<script')

        dish.name = 'Fresh soup'
        dish.save()
        with patch('meny.templatetags.rsbuild._load_manifest') as load_manifest:
            updated = self.client.get(url)
        self.assertContains(updated, 'Fresh soup')
        self.assertIn('no-store', updated.headers['Cache-Control'])
        load_manifest.assert_not_called()

    def test_fragment_receives_current_login_state(self):
        menu = Menu.objects.create(name='Lunch')
        url = reverse('menu-pages', args=[menu.pk])
        self.assertFalse(self.client.get(url).context['user'].is_authenticated)
        user = get_user_model().objects.create_user(username='menu-reader')
        self.client.force_login(user)
        self.assertEqual(self.client.get(url).context['user'], user)

    def test_fragment_rejects_unsupported_methods_and_unknown_menu_returns_404(self):
        menu = Menu.objects.create(name='Lunch')
        self.assertEqual(self.client.get(reverse('menu-pages', args=[menu.pk + 1])).status_code, 404)
        self.assertEqual(self.client.put(reverse('menu-pages', args=[menu.pk])).status_code, 405)

    def test_index_renders_menu_data_in_turnpage_markup(self):
        menu = Menu.objects.create(
            id=2, name='Indisk meny', show_toc=True,
            description='Utforsk vår indiske meny.',
            content='Menu-level content should not be used yet.',
            cover_content='Velkommen. Bla gjennom menyen og finn noe godt.',
            back_cover_title='Takk for besøket',
            back_cover_content='Vi håper du hadde et godt måltid.',
        )
        front_cover_page = MenuPage.objects.create(
            menu=menu, name='Forside', heading='Indisk meny',
            decorative_title='Velkommen', position=0,
            descriptive_title='Indisk meny',
            content=menu.cover_content,
            layout=MenuPage.Layout.COVER, image='menus/pages/cover.jpg',
            overlay=MenuPage.Overlay.NONE, text_shadow=True,
        )
        MenuPage.objects.create(
            menu=menu, name='Småretter', heading='Småretter',
            decorative_title='Små biter, store smil', position=1,
        )
        panorama_page = MenuPage.objects.create(
            menu=menu, name='Curry', heading='Curry',
            decorative_title='Varme krydder, gode øyeblikk',
            descriptive_title='Curryretter', position=2,
            layout=MenuPage.Layout.PANORAMA, image='menus/pages/panorama.jpg',
            overlay=MenuPage.Overlay.WHITE, text_shadow=True,
        )
        MenuPage.objects.create(
            menu=menu, name='Tandoor', heading='Tandoor',
            decorative_title='Del gode smaker', position=3,
        )
        MenuPage.objects.create(
            menu=menu, name='Dessert og drikke', heading='Dessert og drikke',
            decorative_title='Søt avslutning, gode minner', position=4,
        )
        back_cover_page = MenuPage.objects.create(
            menu=menu, name='Bakside', heading=menu.back_cover_title,
            decorative_title='Vi sees snart', descriptive_title=menu.back_cover_title,
            content=menu.back_cover_content, position=5,
            layout=MenuPage.Layout.COVER, text_shadow=True,
        )
        Dish.objects.create(
            menu_page=panorama_page, name='Vegetarsamosa', description='Krydret potet.',
            price='109.00', allergens=['gluten'],
        )

        with override_settings(FRONTEND_ENABLED=False):
            response = self.client.get('/')

        self.assertContains(response, 'data-page-turn')
        self.assertContains(response, '<a class="skip-link" href="#book">Hopp til menyen</a>', html=True)
        self.assertContains(response, 'data-book-canvas')
        self.assertContains(response, 'data-book-pages')
        self.assertContains(response, 'data-toc="Innhold"')
        self.assertNotContains(response, 'Utforsk vår indiske meny.')
        self.assertContains(response, 'class="slide cover-slide front-cover background-slide cover"')
        self.assertContains(response, 'class="front-cover-content stack"', count=1)
        self.assertContains(response, 'class="slide cover-slide back-cover"')
        self.assertContains(response, 'aria-labelledby="forside"')
        self.assertContains(response, 'aria-labelledby="bakside"')
        self.assertContains(response, 'data-overlay="none" data-text-shadow')
        self.assertContains(response, 'data-overlay="white" data-text-shadow data-panorama')
        self.assertContains(response, 'data-panorama', count=2)
        self.assertContains(response, '<p class="slide-label">Velkommen</p>', html=True)
        self.assertContains(
            response,
            '<p class="slide-label">Varme krydder, gode øyeblikk</p>',
            html=True,
        )
        self.assertContains(response, '<h2 id="curry">Curryretter</h2>', html=True)
        self.assertContains(response, 'Velkommen. Bla gjennom menyen og finn noe godt.')
        self.assertContains(response, 'id="curry"')
        self.assertContains(response, 'aria-labelledby="curry"')
        self.assertNotContains(response, 'menu-page-')
        self.assertContains(response, 'Takk for besøket')
        self.assertContains(response, 'Vi håper du hadde et godt måltid.')
        self.assertNotContains(response, 'Utforsk menyen og finn din neste favoritt.')
        self.assertContains(response, f'src="{front_cover_page.image.url}"')
        self.assertContains(response, f'src="{panorama_page.image.url}"')
        self.assertContains(response, 'class="spread-image spread-background"')
        self.assertContains(response, 'class="slide background-slide"')
        self.assertContains(response, '<span data-page-number>03</span> /', html=False)
        self.assertContains(response, '<span data-page-number>04</span> /', html=False)
        self.assertContains(
            response,
            '<h2 id="bakside">Takk for besøket</h2>',
            html=True,
        )
        self.assertNotContains(response, 'Menu-level content should not be used yet.')
        self.assertContains(response, 'Vi håper du hadde et godt måltid.')
        self.assertContains(response, 'Vegetarsamosa')
        self.assertContains(response, '109 kr')
        self.assertContains(response, 'Allergener: Gluten')
        self.assertEqual(front_cover_page.position, 0)
        self.assertEqual(back_cover_page.position, 5)


class MenuPaginationTests(TestCase):
    def setUp(self):
        self.menu = Menu.objects.create(id=2, name='Lunch')
        MenuPage.objects.create(
            menu=self.menu, name='Front', heading='Lunch', decorative_title='Welcome',
            layout='cover', position=0,
        )
        self.category = MenuPage.objects.create(
            menu=self.menu, name='Curry', heading='Curry', decorative_title='Warm spices',
            content='Category introduction', position=1,
        )
        MenuPage.objects.create(
            menu=self.menu, name='Back', heading='Thanks', decorative_title='See you soon',
            layout='cover', position=10,
        )

    def test_hidden_dishes_are_filtered_before_customer_pagination_but_remain_editable_for_staff(self):
        dishes = [
            Dish.objects.create(menu_page=self.category, name=f'Dish {index}', position=index,
                                is_visible=index % 2 == 0, price='99.00')
            for index in range(9)
        ]
        ordinary = get_user_model().objects.create_user(username='visibility-customer')
        for user in (None, ordinary):
            if user:
                self.client.force_login(user)
            else:
                self.client.logout()
            for url in ('/', reverse('menu-pages', args=[self.menu.pk])):
                response = self.client.get(url)
                for dish in dishes:
                    if dish.is_visible:
                        self.assertContains(response, f'<h3>{dish.name}</h3>', html=True)
                    else:
                        self.assertNotContains(response, dish.name)
                self.assertContains(response, 'data-cart-action="add"', count=5)
                self.assertNotContains(response, 'data-dish-action="visibility"')
        pages = get_menu_pages(self.menu)[1:-1]
        self.assertEqual([len(page.turnpage_dishes) for page in pages], [4, 1])
        self.assertEqual(
            [dish.pk for page in pages for dish in page.turnpage_dishes],
            [dish.pk for dish in dishes if dish.is_visible],
        )
        for is_staff, is_superuser in ((True, False), (False, True)):
            editor = get_user_model().objects.create_user(
                username=f'visibility-editor-{is_staff}', is_staff=is_staff, is_superuser=is_superuser,
            )
            self.client.force_login(editor)
            response = self.client.get(reverse('menu-pages', args=[self.menu.pk]))
            self.assertContains(response, 'data-dish-action="visibility"', count=9)
            self.assertContains(response, '<h3>Dish 1 (skjult)</h3>', html=True)
            self.assertContains(response, 'aria-label="Vis Dish 1 for kunder"')
            self.assertContains(response, 'aria-label="Skjul Dish 0 for kunder"')
            for icon in ('eyeopen', 'eyedisabled'):
                self.assertContains(response, f'<use href="#{icon}" xlink:href="#{icon}"></use>')

    def test_hiding_a_parent_also_filters_independently_visible_manual_continuations(self):
        self.category.is_visible = False
        self.category.save()
        manual = MenuPage.objects.create(
            menu=self.menu, name='Manual curry', decorative_title='More curry',
            is_continuation=True, position=2,
        )
        Dish.objects.create(menu_page=manual, name='Secret curry')
        self.assertEqual([page.name for page in get_menu_pages(self.menu)], ['Front', 'Back'])
        self.assertNotContains(self.client.get('/'), 'Secret curry')
        self.assertNotContains(self.client.get(reverse('menu-pages', args=[self.menu.pk])), 'More curry')
        self.assertEqual(len(get_menu_pages(self.menu, include_hidden=True)), 4)

    @override_settings(FRONTEND_ENABLED=False)
    def test_staff_and_superusers_get_edit_controls_across_automatic_continuations(self):
        dishes = [
            Dish.objects.create(menu_page=self.category, name=f'Dish {index}', position=index)
            for index in range(9)
        ]
        for is_staff, is_superuser in ((True, False), (False, True), (True, True)):
            user = get_user_model().objects.create_user(
                username=f'editor-{is_staff}-{is_superuser}',
                is_staff=is_staff, is_superuser=is_superuser,
            )
            self.client.force_login(user)
            for url in ('/', reverse('menu-pages', args=[self.menu.pk])):
                with self.subTest(staff=is_staff, superuser=is_superuser, url=url):
                    response = self.client.get(url)
                    self.assertContains(response, 'data-dish-action="edit"', count=9)
                    self.assertContains(response, 'data-dish-action="up"', count=8)
                    self.assertContains(response, 'data-dish-action="down"', count=8)
                    self.assertNotContains(response, 'data-cart-action')
                    self.assertContains(response, 'id="curry-to"')
                    for index, dish in enumerate(dishes):
                        for action, expected in (
                            ('edit', True), ('up', index > 0), ('down', index < 8),
                        ):
                            hook = f'data-dish-action="{action}" data-dish-id="{dish.pk}"'
                            if expected:
                                self.assertContains(response, hook, count=1)
                            else:
                                self.assertNotContains(response, hook)
                    for label in ('Rediger Dish 0', 'Flytt Dish 4 opp', 'Flytt Dish 3 ned'):
                        self.assertContains(response, f'aria-label="{label}"')
                    for symbol in ('edit', 'arrowup', 'arrowdown'):
                        self.assertContains(response, f'<use href="#{symbol}" xlink:href="#{symbol}">')

    @override_settings(FRONTEND_ENABLED=False)
    def test_anonymous_and_ordinary_users_keep_cart_buttons(self):
        Dish.objects.create(menu_page=self.category, name='Soup', price='99.00')
        ordinary_user = get_user_model().objects.create_user(username='ordinary-reader')
        for user in (None, ordinary_user):
            if user:
                self.client.force_login(user)
            else:
                self.client.logout()
            for url in ('/', reverse('menu-pages', args=[self.menu.pk])):
                with self.subTest(user=user, url=url):
                    response = self.client.get(url)
                    self.assertContains(response, 'data-cart-action="add"', count=1)
                    self.assertNotContains(response, 'data-cart-action="remove"')
                    self.assertNotContains(response, 'data-dish-action')

    def test_staff_single_dish_has_edit_button_but_no_move_buttons(self):
        Dish.objects.create(menu_page=self.category, name='Daily special')
        user = get_user_model().objects.create_user(username='staff-reader', is_staff=True)
        self.client.force_login(user)
        response = self.client.get(reverse('menu-pages', args=[self.menu.pk]))
        self.assertContains(response, 'data-dish-action="edit"', count=1)
        self.assertNotContains(response, 'data-dish-action="up"')
        self.assertNotContains(response, 'data-dish-action="down"')
        self.assertNotContains(response, 'data-cart-action')

    def test_automatic_pages_split_ordered_dishes_at_both_limits_without_saving_pages(self):
        for count, sizes in [
            (0, [0]), (4, [4]), (5, [4, 1]), (9, [4, 5]),
            (10, [4, 5, 1]), (14, [4, 5, 5]),
        ]:
            with self.subTest(count=count):
                self.category.dishes.all().delete()
                dishes = [
                    Dish.objects.create(
                        menu_page=self.category, name=f'Dish {index}', position=count - index,
                    )
                    for index in range(count)
                ][::-1]
                menu = Menu.objects.prefetch_related('pages__dishes').get(pk=self.menu.pk)
                with self.assertNumQueries(0):
                    pages = get_menu_pages(menu)[1:-1]
                    repeated = get_menu_pages(menu)[1:-1]
                self.assertEqual([len(page.turnpage_dishes) for page in pages], sizes)
                self.assertEqual(
                    [dish for page in pages for dish in page.turnpage_dishes], dishes,
                )
                expected_slugs = ['curry', 'curry-to', 'curry-tre'][:len(sizes)]
                self.assertEqual([page.slug for page in pages], expected_slugs)
                self.assertEqual([page.slug for page in repeated], expected_slugs)
                self.assertEqual(self.menu.pages.count(), 3)
                self.assertEqual(self.category.dishes.count(), count)
                self.assertTrue(all(page.is_continuation for page in pages[1:]))
                self.assertEqual(list(menu.pages.all())[1].slug, 'curry')
                self.assertFalse(list(menu.pages.all())[1].is_continuation)

        with override_settings(FRONTEND_ENABLED=False):
            initial = self.client.get('/')
        fragment = self.client.get(reverse('menu-pages', args=[self.menu.pk]))
        for response in (initial, fragment):
            self.assertContains(response, '<h2 id="curry">Curry</h2>', count=1, html=True)
            self.assertContains(response, 'Category introduction', count=1)
            self.assertContains(response, '<p class="slide-label">Warm spices</p>', count=3, html=True)
            for slug in ('curry-to', 'curry-tre'):
                self.assertContains(response, f'data-continuation data-toc-exclude id="{slug}"')
            for dish in dishes:
                self.assertContains(response, f'<h3>{dish.name}</h3>', count=1, html=True)
            self.assertContains(response, '<span data-page-number>04</span>', html=True)

    def test_manual_pages_reserve_their_hashes_and_also_allow_automatic_overflow(self):
        manual = MenuPage.objects.create(
            menu=self.menu, name='Curry', is_continuation=True,
            decorative_title='More warm spices', position=2,
        )
        for page, count in ((self.category, 10), (manual, 6)):
            for index in range(count):
                Dish.objects.create(menu_page=page, name=f'{page.slug} dish {index}', position=index)
        pages = get_menu_pages(self.menu)[1:-1]
        self.assertEqual(
            [page.slug for page in pages],
            ['curry', 'curry-tre', 'curry-fire', 'curry-to', 'curry-fem'],
        )
        self.assertEqual([len(page.turnpage_dishes) for page in pages], [4, 5, 1, 5, 1])
        self.assertEqual(len({page.turnpage_key for page in pages}), 5)
        self.assertEqual([page.turnpage_page_number for page in pages], [2, 3, 4, 5, 6])
        self.assertTrue(all(page.turnpage_total == 6 for page in pages))
        manual.refresh_from_db()
        self.assertEqual(manual.slug, 'curry-to')
        self.assertEqual(self.menu.pages.count(), 4)

    def test_menu_limits_can_be_changed_or_disabled_but_not_set_to_zero(self):
        for index in range(10):
            Dish.objects.create(menu_page=self.category, name=f'Dish {index}', position=index)
        self.menu.max_per_page = 2
        self.menu.max_per_extra_page = 3
        self.assertEqual(
            [len(page.turnpage_dishes) for page in get_menu_pages(self.menu)[1:-1]],
            [2, 3, 3, 2],
        )
        for first_limit, extra_limit in ((None, 5), (4, None), (None, None)):
            with self.subTest(first=first_limit, extra=extra_limit):
                self.menu.max_per_page = first_limit
                self.menu.max_per_extra_page = extra_limit
                pages = get_menu_pages(self.menu)[1:-1]
                self.assertEqual([len(page.turnpage_dishes) for page in pages], [10])
        form_class = modelform_factory(
            Menu, fields=('name', 'max_per_page', 'max_per_extra_page'),
        )
        for invalid in (0, -1):
            form = form_class(data={
                'name': 'Lunch', 'max_per_page': invalid, 'max_per_extra_page': invalid,
            })
            self.assertFalse(form.is_valid())
            self.assertIn('max_per_page', form.errors)
            self.assertIn('max_per_extra_page', form.errors)

    def test_panorama_overflow_preserves_a_single_image_pair_and_does_not_split_covers(self):
        self.category.layout = 'panorama'
        self.category.image = 'menus/pages/curry.jpg'
        self.category.save()
        for page in self.menu.pages.all():
            for index in range(10):
                Dish.objects.create(menu_page=page, name=f'{page.name} dish {index}', position=index)
        pages = get_menu_pages(self.menu)
        self.assertEqual(
            [len(page.turnpage_dishes) for page in pages], [10, 4, 5, 1, 10],
        )
        self.assertTrue(pages[1].turnpage_spread)
        self.assertTrue(pages[2].turnpage_spread_partner)
        self.assertFalse(pages[3].turnpage_spread_partner)
        self.assertEqual([bool(page.image) for page in pages], [False, True, False, False, False])
        self.assertEqual(
            [page.turnpage_page_number for page in pages[1:-1]], [3, 4, 5],
        )
        self.assertTrue(all(page.turnpage_total == 6 for page in pages))
        response = self.client.get(reverse('menu-pages', args=[self.menu.pk]))
        self.assertContains(response, 'data-panorama', count=2)
        self.assertContains(response, 'class="spread-image spread-background"', count=1)

    def test_numbers_include_alignment_and_final_padding_without_contents(self):
        self.menu.show_toc = False
        self.menu.save()
        MenuPage.objects.create(
            menu=self.menu, name='Starters', heading='Starters', decorative_title='Small bites',
            position=0,
        )
        self.category.layout = 'panorama'
        self.category.image = 'menus/pages/curry.jpg'
        self.category.save()
        for index in range(9):
            Dish.objects.create(menu_page=self.category, name=f'Dish {index}', position=index)
        pages = get_menu_pages(self.menu)
        self.assertEqual([page.slug for page in pages], ['front', 'starters', 'curry', 'curry-to', 'back'])
        self.assertEqual(
            [page.turnpage_page_number for page in pages[1:-1]], [1, 3, 4],
        )
        self.assertTrue(all(page.turnpage_total == 4 for page in pages))

        self.category.layout = 'split'
        self.category.image = ''
        self.category.save()
        pages = get_menu_pages(self.menu)
        self.assertEqual(
            [page.turnpage_page_number for page in pages[1:-1]], [1, 2, 3],
        )
        self.assertTrue(all(page.turnpage_total == 4 for page in pages))
        response = self.client.get(reverse('menu-pages', args=[self.menu.pk]))
        self.assertNotContains(response, 'data-toc="')
        self.assertContains(response, '<span data-page-total>04</span>', count=3, html=True)


class RuntimeSettingsTests(SimpleTestCase):
    def configuration(self, environment=None, contents=''):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / '.env'
            env_file.write_text(contents)
            values = {'DJANGO_ENV_FILE': str(env_file), **(environment or {})}
            with patch.dict(os.environ, values, clear=True):
                return runpy.run_path(str(Path(__file__).with_name('local_settings.py')))

    def test_dotenv_configures_postgresql_and_preserves_literal_passwords(self):
        config = self.configuration(contents=(
            'DJANGO_DEBUG=false\n'
            'DJANGO_SECRET_KEY=test-only-key\n'
            'DJANGO_ALLOWED_HOSTS=example.com,192.0.2.1\n'
            'DJANGO_DATABASE_NAME=meny\n'
            'DJANGO_DATABASE_USER=app_user\n'
            'DJANGO_DATABASE_PASSWORD="literal-${UNCHANGED}-password"\n'
            'DJANGO_DATABASE_HOST=database.example\n'
            'DJANGO_DATABASE_PORT=5432\n'
        ))
        self.assertFalse(config['DEBUG'])
        self.assertEqual(config['ALLOWED_HOSTS'], ['example.com', '192.0.2.1'])
        database = config['DATABASES']['default']
        self.assertEqual(database['ENGINE'], 'django.db.backends.postgresql')
        self.assertEqual(database['NAME'], 'meny')
        self.assertEqual(database['PASSWORD'], 'literal-${UNCHANGED}-password')

    def test_process_environment_wins_over_dotenv(self):
        config = self.configuration(
            {
                'DJANGO_DEBUG': 'true',
                'DJANGO_SECRET_KEY': 'process-test-key',
                'DJANGO_INTERNAL_AUTH_TOKEN': 'process-test-token',
            },
            'DJANGO_DEBUG=false\nDJANGO_SECRET_KEY=file-test-key\n'
            'DJANGO_INTERNAL_AUTH_TOKEN=file-test-token\n',
        )
        self.assertTrue(config['DEBUG'])
        self.assertEqual(config['SECRET_KEY'], 'process-test-key')
        self.assertEqual(config['INTERNAL_AUTH_TOKEN'], 'process-test-token')

    def test_unconfigured_development_keeps_base_sqlite_database(self):
        self.assertNotIn('DATABASES', self.configuration())

    def test_frontend_defaults_to_directory_presence_and_can_be_overridden(self):
        for present in (False, True):
            with self.subTest(present=present), patch.object(Path, 'is_dir', return_value=present):
                config = self.configuration()
                self.assertEqual(config['FRONTEND_ENABLED'], present)
                if not present:
                    self.assertEqual(config['CORS_ALLOWED_ORIGINS'], [])
                for value, expected in [('false', False), ('true', True)]:
                    config = self.configuration({'DJANGO_FRONTEND_ENABLED': value})
                    self.assertEqual(config['FRONTEND_ENABLED'], expected)

    def test_development_cors_allows_loopback_and_configured_frontend_origin(self):
        config = self.configuration({
            'DJANGO_FRONTEND_ENABLED': 'true',
            'RSBUILD_BASE_URL': 'http://192.0.2.10:3300/assets/',
        })
        self.assertEqual(config['CORS_ALLOWED_ORIGINS'], [
            'http://localhost:3000', 'http://127.0.0.1:3000', 'http://192.0.2.10:3300',
        ])
        self.assertFalse(config['CORS_ALLOW_CREDENTIALS'])
        self.assertEqual(config['CSRF_TRUSTED_ORIGINS'], [])

    def test_cors_defaults_do_not_override_explicit_configuration_or_production(self):
        for value, expected in [
            ('https://frontend.example', ['https://frontend.example']), ('', []),
        ]:
            with self.subTest(value=value):
                config = self.configuration({'DJANGO_CORS_ALLOWED_ORIGINS': value})
                self.assertEqual(config['CORS_ALLOWED_ORIGINS'], expected)
        config = self.configuration({
            'DJANGO_DEBUG': 'false', 'DJANGO_SECRET_KEY': 'test-only-key',
            'DJANGO_DATABASE_NAME': 'production-database',
            'RSBUILD_BASE_URL': 'https://frontend.example/assets/',
        })
        self.assertEqual(config['CORS_ALLOWED_ORIGINS'], [])

    def test_development_sqlite_broker_is_separate_from_djangos_database(self):
        for contents in ['', 'CELERY_BROKER_URL=\n']:
            with self.subTest(contents=contents):
                config = self.configuration(contents=contents)
                self.assertNotIn('DATABASES', config)
                self.assertTrue(config['CELERY_BROKER_URL'].startswith('sqla+sqlite:///'))
                self.assertTrue(config['CELERY_BROKER_URL'].endswith('/celery-broker.sqlite3'))

    def test_production_and_explicit_brokers_do_not_switch_to_sqlite(self):
        config = self.configuration({
            'DJANGO_DEBUG': 'false', 'DJANGO_SECRET_KEY': 'test-only-key',
            'DJANGO_DATABASE_NAME': 'production-database',
        })
        self.assertEqual(config['CELERY_BROKER_URL'], 'amqp://localhost')
        config = self.configuration({'CELERY_BROKER_URL': 'amqp://dev-broker/dev'})
        self.assertEqual(config['CELERY_BROKER_URL'], 'amqp://dev-broker/dev')

    def test_memcached_is_opt_in(self):
        for environment in [{}, {'DJANGO_MEMCACHED_LOCATION': ''}]:
            with self.subTest(environment=environment):
                self.assertNotIn('CACHES', self.configuration(environment))

    def test_django_mount_prefix_configures_reversed_urls(self):
        self.assertIsNone(self.configuration()['FORCE_SCRIPT_NAME'])
        config = self.configuration({'DJANGO_SCRIPT_NAME': '/django'})
        self.assertEqual(config['FORCE_SCRIPT_NAME'], '/django')

    def test_backend_locations_load_from_env_in_dev_and_production(self):
        self.assertEqual(self.configuration()['TS_BACKEND_URL'], '')
        self.assertEqual(self.configuration()['TS_WS_BACKEND_URL'], '')
        for debug, http_url, ws_url in [
            ('true', 'http://localhost:8001/', 'ws://localhost:8002/'),
            ('false', '/v1/', '/socket/'),
        ]:
            with self.subTest(debug=debug):
                config = self.configuration(contents=(
                    f'DJANGO_DEBUG={debug}\n'
                    'DJANGO_SECRET_KEY=test-only-key\n'
                    'DJANGO_DATABASE_NAME=test-only-database\n'
                    f'DJANGO_TS_BACKEND_URL={http_url}\n'
                    f'DJANGO_TS_WS_BACKEND_URL={ws_url}\n'
                ))
                self.assertEqual(config['TS_BACKEND_URL'], http_url)
                self.assertEqual(config['TS_WS_BACKEND_URL'], ws_url)

    def test_memcached_uses_distinct_deployment_namespaces(self):
        keys = []
        for prefix in ['meny', 'meny_staging']:
            config = self.configuration(contents=(
                'DJANGO_MEMCACHED_LOCATION=127.0.0.1:11211\n'
                f'DJANGO_CACHE_KEY_PREFIX={prefix}\n'
            ))
            backend = config['CACHES']['default']
            self.assertEqual(
                backend['BACKEND'], 'django.core.cache.backends.memcached.PyMemcacheCache',
            )
            cache = PyMemcacheCache(backend['LOCATION'], backend)
            keys.append(cache.make_key('same-key'))
        self.assertNotEqual(*keys)

    def test_production_requires_secret_and_database(self):
        for environment in [
            {'DJANGO_DEBUG': 'false'},
            {'DJANGO_DEBUG': 'false', 'DJANGO_SECRET_KEY': ''},
            {'DJANGO_DEBUG': 'false', 'DJANGO_SECRET_KEY': 'test-only-key'},
        ]:
            with self.subTest(environment=environment):
                with self.assertRaises(ImproperlyConfigured):
                    self.configuration(environment)

    def test_legacy_database_variables_still_work(self):
        config = self.configuration({
            'DATABASE_NAME': 'legacy.sqlite3',
            'DATABASE_ENGINE': 'django.db.backends.sqlite3',
        })
        self.assertEqual(config['DATABASES']['default']['ENGINE'], 'django.db.backends.sqlite3')
        self.assertEqual(config['DATABASES']['default']['NAME'], 'legacy.sqlite3')

    def test_persistent_files_and_proxy_configuration(self):
        config = self.configuration({
            'DJANGO_DEBUG': 'false',
            'DJANGO_SECRET_KEY': 'test-only-key',
            'DJANGO_DATABASE_NAME': 'meny',
            'DJANGO_STATIC_ROOT': '/srv/meny/static',
            'DJANGO_MEDIA_ROOT': '/srv/meny/media',
            'DJANGO_TRUST_PROXY_HEADERS': 'true',
        })
        self.assertEqual(config['RSBUILD_MANIFEST'], Path('/srv/meny/static/manifest.json'))
        self.assertEqual(config['MEDIA_ROOT'], '/srv/meny/media')
        self.assertEqual(config['FILE_UPLOAD_PERMISSIONS'], 0o640)
        self.assertEqual(config['FILE_UPLOAD_DIRECTORY_PERMISSIONS'], 0o2750)
        self.assertEqual(config['SECURE_PROXY_SSL_HEADER'], ('HTTP_X_FORWARDED_PROTO', 'https'))

    def test_subpath_deployment_isolates_assets_and_browser_cookies(self):
        config = self.configuration({
            'DJANGO_STATIC_URL': '/meny/static/',
            'DJANGO_MEDIA_URL': '/meny/media/',
            'DJANGO_SESSION_COOKIE_NAME': 'meny_sessionid',
            'DJANGO_CSRF_COOKIE_NAME': 'meny_csrftoken',
            'DJANGO_SESSION_COOKIE_PATH': '/meny/',
            'DJANGO_CSRF_COOKIE_PATH': '/meny/',
        })
        self.assertEqual(config['STATIC_URL'], '/meny/static/')
        self.assertEqual(config['MEDIA_URL'], '/meny/media/')
        self.assertEqual(config['SESSION_COOKIE_NAME'], 'meny_sessionid')
        self.assertEqual(config['CSRF_COOKIE_NAME'], 'meny_csrftoken')
        self.assertEqual(config['SESSION_COOKIE_PATH'], '/meny/')
        self.assertEqual(config['CSRF_COOKIE_PATH'], '/meny/')


class DevelopmentCorsTests(SimpleTestCase):
    @override_settings(CORS_ALLOWED_ORIGINS=['http://localhost:3000', 'http://127.0.0.1:3000'])
    def test_port_3000_receives_cors_headers_on_real_responses(self):
        for origin in ['http://localhost:3000', 'http://127.0.0.1:3000']:
            with self.subTest(origin=origin):
                response = self.client.get('/admin/login/', HTTP_ORIGIN=origin)
                self.assertEqual(response['Access-Control-Allow-Origin'], origin)
        response = self.client.get('/admin/login/', HTTP_ORIGIN='http://localhost:3001')
        self.assertNotIn('Access-Control-Allow-Origin', response)

    @override_settings(CORS_ALLOWED_ORIGINS=['http://localhost:3000'])
    def test_frontend_preflight_allows_post_and_csrf_header(self):
        response = self.client.options(
            '/', HTTP_ORIGIN='http://localhost:3000',
            HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST',
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS='content-type,x-csrftoken',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Access-Control-Allow-Origin'], 'http://localhost:3000')
        self.assertIn('POST', response['Access-Control-Allow-Methods'])
        self.assertIn('x-csrftoken', response['Access-Control-Allow-Headers'])


class CeleryIntegrationTests(SimpleTestCase):
    @override_settings(
        CELERY_TASK_ALWAYS_EAGER=True,
        CELERY_TASK_EAGER_PROPAGATES=True,
        CELERY_BROKER_URL='memory://',
    )
    def test_shared_task_uses_django_celery_configuration(self):
        self.assertTrue(app.conf.task_always_eager)
        result = runtime_test_task.delay('template')
        self.assertEqual(result.get(), 'TEMPLATE')


@override_settings(
    WS_INTERNAL_URL='http://127.0.0.1:8002/',
    WS_INTERNAL_NOTIFY_TOKEN='test-only-notify',
)
class NotificationTaskTests(SimpleTestCase):
    def setUp(self):
        self.transport_patch = patch('meny.tasks._opener.open')
        self.transport = self.transport_patch.start()
        self.addCleanup(self.transport_patch.stop)
        self.transport.return_value.__enter__.return_value.status = 202

    def test_chained_notification_authenticates_and_preserves_the_work_result(self):
        result = (runtime_test_task.s('done') | notify.s(42, 'work.finished')).apply().get()
        self.assertEqual(result, 'DONE')
        request = self.transport.call_args.args[0]
        self.assertEqual(request.full_url, 'http://127.0.0.1:8002/internal/notify/')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('Authorization'), 'Bearer test-only-notify')
        self.assertEqual(request.get_header('Content-type'), 'application/json')
        self.assertEqual(json.loads(request.data), {
            'user_id': 42, 'event': 'work.finished', 'result': 'DONE',
        })
        self.assertEqual(self.transport.call_args.kwargs['timeout'], 5)

    def test_missing_sender_configuration_skips_delivery_and_warns_only_at_startup(self):
        for missing in ['WS_INTERNAL_URL', 'WS_INTERNAL_NOTIFY_TOKEN']:
            with self.subTest(missing=missing), override_settings(
                INTERNAL_AUTH_TOKEN='test-only-auth', **{missing: ''},
            ):
                with self.assertLogs('meny.apps', level='WARNING') as logs:
                    apps.get_app_config('meny').ready()
                    self.assertEqual(notify.run('done', 42), 'done')
                    self.assertEqual(notify.run('done', 42), 'done')
                self.assertEqual(len(logs.output), 1)
                self.assertIn('Celery WebSocket notifications are disabled', logs.output[0])
        self.transport.assert_not_called()

    def test_transient_network_and_http_failures_retry(self):
        errors = [URLError('unavailable'), TimeoutError('timed out')]
        errors += [
            HTTPError('http://127.0.0.1:8002/internal/notify/', code, 'temporary', {}, io.BytesIO())
            for code in [429, 500, 503]
        ]
        for error in errors:
            with self.subTest(error=error):
                self.transport.side_effect = error
                with patch.object(notify, 'retry', side_effect=Retry()) as retry:
                    with self.assertRaises(Retry):
                        notify.run('done', 42)
                retry.assert_called_once_with(exc=error, countdown=1)

    def test_permanent_http_failures_do_not_retry(self):
        for code in [400, 403, 404, 413]:
            error = HTTPError(
                'http://127.0.0.1:8002/internal/notify/', code, 'rejected', {}, io.BytesIO(),
            )
            with self.subTest(code=code), patch.object(notify, 'retry') as retry:
                self.transport.side_effect = error
                with self.assertRaises(HTTPError):
                    notify.run('done', 42)
                retry.assert_not_called()

    def test_invalid_or_oversized_notifications_are_rejected_before_delivery(self):
        for result, user_id, event in [
            ('done', 0, 'work.finished'), ('done', True, 'work.finished'),
            ('done', 2**53, 'work.finished'), ('done', '', 'work.finished'),
            ('done', 42, ''), ('x' * 65536, 42, 'work.finished'),
            (float('nan'), 42, 'work.finished'),
        ]:
            with self.subTest(user_id=user_id, event=event), self.assertRaises(ValueError):
                notify.run(result, user_id, event)
        self.transport.assert_not_called()

    def test_unexpected_success_response_is_not_accepted(self):
        self.transport.return_value.__enter__.return_value.status = 200
        with patch.object(notify, 'retry') as retry, self.assertRaises(ValueError):
            notify.run('done', 42)
        retry.assert_not_called()

    def test_redirects_are_not_followed_with_service_credentials(self):
        self.transport_patch.stop()
        requests = []

        class RedirectHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(self.path)
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                self.send_response(302)
                self.send_header('Location', '/redirect-target')
                self.send_header('Content-Length', '0')
                self.end_headers()

            def do_GET(self):
                requests.append(self.path)
                self.send_response(202)
                self.end_headers()

            def log_message(self, format, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), RedirectHandler)
        thread = Thread(target=server.serve_forever)
        thread.start()
        try:
            with override_settings(WS_INTERNAL_URL=f'http://127.0.0.1:{server.server_port}/'):
                with self.assertRaises(HTTPError) as error:
                    notify.run('done', 42)
                self.assertEqual(error.exception.code, 302)
            self.assertEqual(requests, ['/internal/notify/'])
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


class DjangoMountTests(TestCase):
    def setUp(self):
        Menu.objects.create(id=2, name='Test menu')

    @override_settings(FORCE_SCRIPT_NAME='/django')
    def test_homepage_and_admin_respect_the_mount_prefix(self):
        prefix = get_script_prefix()
        self.addCleanup(set_script_prefix, prefix)
        set_script_prefix('/django/')
        response = self.client.get('/')
        self.assertContains(response, '<title>Test menu</title>', html=True)
        response = self.client.get('/admin/login/')
        self.assertContains(response, 'action="/django/admin/login/"')

    def test_body_exposes_backend_urls_in_dev_prod_and_disabled_cases(self):
        for http_url, ws_url in [
            ('http://localhost:8001/', 'ws://localhost:8002/'),
            ('/api/', '/ws/'),
            ('', ''),
        ]:
            with self.subTest(http_url=http_url), override_settings(
                TS_BACKEND_URL=http_url, TS_WS_BACKEND_URL=ws_url,
            ):
                response = self.client.get('/')
                self.assertContains(
                    response,
                    f'<body class="no-js" data-ts-backend-url="{http_url}" data-ts-ws-backend-url="{ws_url}">',
                )


class JobResultsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='job-owner')
        cls.other_user = get_user_model().objects.create_user(username='other-job-owner')
        cls.job = Job.objects.create(user=cls.user, task_id='owned-task')

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse('job-results')
        self.application = Mock()
        self.application.conf.result_backend = 'cache+memory://'
        self.application.backend.get_task_meta.return_value = {'status': 'SUCCESS', 'result': 5}
        application_patch = patch('meny.views.app', self.application)
        application_patch.start()
        self.addCleanup(application_patch.stop)

    def test_requires_a_user_session_and_get_without_querying_results(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.client.force_login(self.user)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response['Allow'], 'GET')
        self.application.backend.get_task_meta.assert_not_called()

    def test_returns_only_owned_job_statuses_and_successful_results(self):
        Job.objects.create(user=self.user, task_id='failed-task')
        Job.objects.create(user=self.user, task_id='pending-task')
        Job.objects.create(user=self.other_user, task_id='private-task')
        metadata = {
            'owned-task': {'status': 'SUCCESS', 'result': {'total': 5}},
            'failed-task': {
                'status': 'FAILURE',
                'result': ValueError('test-only-private-error'),
                'traceback': 'test-only-private-traceback',
            },
            'pending-task': {'status': 'PENDING', 'result': None},
        }
        self.application.backend.get_task_meta.side_effect = lambda task_id, **kwargs: metadata[task_id]
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        data = response.json()
        self.assertEqual(data['count'], 3)
        jobs = {job['task_id']: job for job in data['results']}
        self.assertEqual(set(jobs), set(metadata))
        self.assertEqual(jobs['owned-task']['result'], {'total': 5})
        self.assertEqual(jobs['failed-task']['status'], 'FAILURE')
        self.assertIsNone(jobs['failed-task']['result'])
        self.assertIsNone(jobs['pending-task']['result'])
        self.assertNotIn('test-only-private', response.content.decode())

    def test_paginates_owned_jobs_and_rejects_invalid_pages_without_result_queries(self):
        Job.objects.bulk_create([
            Job(user=self.user, task_id=f'owned-task-{index}') for index in range(25)
        ] + [
            Job(user=self.other_user, task_id=f'private-task-{index}') for index in range(25)
        ])
        expected = list(Job.objects.filter(user=self.user).values_list('task_id', flat=True))
        first = self.client.get(self.url).json()
        self.assertEqual((first['count'], first['page'], first['pages']), (26, 1, 2))
        self.assertEqual([job['task_id'] for job in first['results']], expected[:25])
        self.assertEqual(self.application.backend.get_task_meta.call_count, 25)
        second = self.client.get(self.url, {'page': 2}).json()
        self.assertEqual([job['task_id'] for job in second['results']], expected[25:])
        self.assertEqual(self.application.backend.get_task_meta.call_count, 26)
        self.application.backend.get_task_meta.reset_mock()
        for page, status in [('invalid', 400), ('0', 404), ('3', 404)]:
            with self.subTest(page=page):
                self.assertEqual(self.client.get(self.url, {'page': page}).status_code, status)
        self.application.backend.get_task_meta.assert_not_called()

    def test_unconfigured_storage_returns_503_but_empty_job_lists_still_work(self):
        self.application.conf.result_backend = None
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertIn('no-store', response['Cache-Control'])
        self.application.backend.get_task_meta.assert_not_called()
        self.job.delete()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'], [])

    def test_backend_errors_do_not_expose_exception_details(self):
        self.application.backend.get_task_meta.side_effect = ConnectionError('test-only-private-error')
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('test-only-private-error', response.content.decode())

    def test_reads_results_persisted_in_a_real_sqlite_celery_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            result_app = Celery(
                'job-results-test',
                backend=f'db+sqlite:///{Path(directory) / "results.sqlite3"}',
                set_as_current=False,
            )
            try:
                result_app.backend.store_result(self.job.task_id, {'total': 5}, 'SUCCESS')
                with patch('meny.views.app', result_app):
                    response = self.client.get(self.url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['results'][0]['result'], {'total': 5})
            finally:
                result_app.close()

    def test_non_json_results_return_a_controlled_error(self):
        self.application.backend.get_task_meta.return_value = {'status': 'SUCCESS', 'result': b'bytes'}
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'error': 'Unable to encode task results'})


@override_settings(
    INTERNAL_AUTH_TOKEN='test-only-service-token',
    WS_INTERNAL_URL='http://127.0.0.1:8002/',
    WS_INTERNAL_NOTIFY_TOKEN='test-only-notify',
)
class InternalAuthenticationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='auth-user')

    def setUp(self):
        self.url = reverse('auth')
        self.headers = {'HTTP_AUTHORIZATION': 'Bearer test-only-service-token'}

    def test_valid_service_and_session_return_only_user_id_without_caching(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url, **self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'user_id': self.user.pk})
        self.assertIn('no-store', response['Cache-Control'])

    def test_valid_session_does_not_bypass_service_authentication(self):
        self.client.force_login(self.user)
        for authorization in ['', 'Bearer wrong-token', 'Basic test-only-service-token', 'Bearer \u00e9']:
            with self.subTest(authorization=authorization):
                response = self.client.get(self.url, HTTP_AUTHORIZATION=authorization)
                self.assertEqual(response.status_code, 403)
                self.assertIn('no-store', response['Cache-Control'])

    @override_settings(INTERNAL_AUTH_TOKEN='')
    def test_unconfigured_endpoint_is_disabled_even_with_a_valid_session(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url, HTTP_AUTHORIZATION='Bearer ')
        self.assertEqual(response.status_code, 503)
        self.assertIn('no-store', response['Cache-Control'])

    def test_service_token_without_a_valid_session_is_rejected(self):
        for cookie in [None, 'invalid-session']:
            with self.subTest(cookie=cookie):
                self.client.cookies.clear()
                if cookie:
                    self.client.cookies[settings.SESSION_COOKIE_NAME] = cookie
                response = self.client.get(self.url, **self.headers)
                self.assertEqual(response.status_code, 401)
                self.assertIn('no-store', response['Cache-Control'])

    def test_logged_out_session_cookie_cannot_be_replayed(self):
        self.client.force_login(self.user)
        session_cookie = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.client.logout()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = session_cookie
        response = self.client.get(self.url, **self.headers)
        self.assertEqual(response.status_code, 401)

    def test_non_get_requests_are_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, **self.headers)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response['Allow'], 'GET')
        self.assertIn('no-store', response['Cache-Control'])

    @override_settings(INTERNAL_AUTH_TOKEN='')
    def test_missing_token_warns_at_startup_not_per_request(self):
        with self.assertLogs('meny.apps', level='WARNING') as logs:
            apps.get_app_config('meny').ready()
            for _ in range(2):
                self.assertEqual(self.client.get(self.url).status_code, 503)
        self.assertEqual(len(logs.output), 1)
        self.assertIn('DJANGO_INTERNAL_AUTH_TOKEN is not set', logs.output[0])

    def test_configured_token_does_not_warn_at_startup(self):
        with self.assertNoLogs('meny.apps', level='WARNING'):
            apps.get_app_config('meny').ready()

    @override_settings(
        SESSION_COOKIE_NAME='meny_sessionid', SESSION_COOKIE_PATH='/meny/',
        CSRF_COOKIE_NAME='meny_csrftoken', CSRF_COOKIE_PATH='/meny/',
        STATIC_URL='/meny/static/',
    )
    def test_named_session_and_admin_cookie_do_not_use_the_other_apps_cookie(self):
        self.client.force_login(self.user)
        self.client.cookies['sessionid'] = 'unrelated-prosango-session'
        response = self.client.get(self.url, **self.headers)
        self.assertEqual(response.json(), {'user_id': self.user.pk})
        response = self.client.get('/admin/login/')
        self.assertContains(response, '/meny/static/admin/css/base.css')
        self.assertIn('meny_csrftoken', response.cookies)
        self.assertEqual(response.cookies['meny_csrftoken']['path'], '/meny/')
        self.assertNotIn('csrftoken', response.cookies)


@override_settings(FRONTEND_ENABLED=False, WS_INTERNAL_URL='', WS_INTERNAL_NOTIFY_TOKEN='')
class OrderLoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for username, flags in [
            ('login-staff', {'is_staff': True}),
            ('login-super', {'is_superuser': True}),
            ('login-customer', {}),
            ('login-inactive', {'is_staff': True, 'is_active': False}),
        ]:
            get_user_model().objects.create_user(
                username=username, password='isolated-login-test-password', **flags,
            )

    def test_orders_redirect_to_a_dedicated_login_with_accessible_fields(self):
        self.assertRedirects(
            self.client.get('/orders/'), '/orders/login/?next=/orders/',
            fetch_redirect_response=False,
        )
        response = self.client.get(reverse('orders-login'), {'next': '/orders/'})
        self.assertContains(response, '<title>Logg inn · Bestillinger</title>', html=True)
        self.assertContains(response, 'autocomplete="username"')
        self.assertContains(response, 'autocomplete="current-password"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'name="next" value="/orders/"')
        self.assertContains(response, 'for="id_username"')
        self.assertContains(response, 'for="id_password"')

    def test_staff_and_non_staff_superusers_can_log_in(self):
        for username in ['login-staff', 'login-super']:
            with self.subTest(username=username):
                self.client.logout()
                response = self.client.post(reverse('orders-login'), {
                    'username': username, 'password': 'isolated-login-test-password',
                })
                self.assertRedirects(response, reverse('orders'))
                user = get_user_model().objects.get(username=username)
                self.assertEqual(self.client.session['_auth_user_id'], str(user.pk))
                self.assertEqual(self.client.get(reverse('order-list')).status_code, 200)

    def test_invalid_non_staff_and_inactive_accounts_cannot_log_in(self):
        for username, password in [
            ('login-staff', 'wrong-password'),
            ('login-customer', 'isolated-login-test-password'),
            ('login-inactive', 'isolated-login-test-password'),
        ]:
            with self.subTest(username=username):
                response = self.client.post(reverse('orders-login'), {
                    'username': username, 'password': password,
                })
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].non_field_errors())
                self.assertNotIn('_auth_user_id', self.client.session)
                self.assertEqual(self.client.get(reverse('order-list')).status_code, 401)

    def test_login_requires_csrf_and_rejects_an_external_next_url(self):
        client = Client(enforce_csrf_checks=True)
        url = reverse('orders-login')
        data = {
            'username': 'login-staff', 'password': 'isolated-login-test-password',
            'next': 'https://example.com/orders/',
        }
        self.assertEqual(client.post(url, data).status_code, 403)
        client.get(url)
        token = client.cookies[settings.CSRF_COOKIE_NAME].value
        response = client.post(url, data, HTTP_X_CSRFTOKEN=token)
        self.assertRedirects(response, reverse('orders'), fetch_redirect_response=False)

    def test_logout_ends_the_session_and_returns_to_the_order_login(self):
        self.client.force_login(get_user_model().objects.get(username='login-staff'))
        response = self.client.get(reverse('orders'))
        self.assertContains(response, 'action="/orders/logout/"')
        self.assertContains(response, '<button type="submit">Logg ut</button>', html=True)
        url = reverse('orders-logout')
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertIn('_auth_user_id', self.client.session)
        self.assertRedirects(self.client.post(url), reverse('orders-login'))
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.get(reverse('order-list')).status_code, 401)
        self.assertRedirects(
            self.client.get(reverse('orders')), '/orders/login/?next=/orders/',
            fetch_redirect_response=False,
        )

    def test_logout_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(get_user_model().objects.get(username='login-staff'))
        client.get(reverse('orders'))
        url = reverse('orders-logout')
        self.assertEqual(client.post(url).status_code, 403)
        self.assertIn('_auth_user_id', client.session)
        token = client.cookies[settings.CSRF_COOKIE_NAME].value
        response = client.post(url, HTTP_X_CSRFTOKEN=token)
        self.assertRedirects(response, reverse('orders-login'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', client.session)

    @override_settings(FORCE_SCRIPT_NAME='/django')
    def test_order_login_respects_the_mount_prefix(self):
        self.addCleanup(set_script_prefix, get_script_prefix())
        set_script_prefix('/django/')
        response = self.client.get('/orders/login/')
        self.assertContains(response, 'action="/django/orders/login/"')
        response = self.client.post('/orders/login/', {
            'username': 'login-staff', 'password': 'isolated-login-test-password',
        })
        self.assertRedirects(response, '/django/orders/', fetch_redirect_response=False)
        response = self.client.get('/orders/')
        self.assertContains(response, 'action="/django/orders/logout/"')
        response = self.client.post('/orders/logout/')
        self.assertRedirects(response, '/django/orders/login/', fetch_redirect_response=False)


class OrderingTests(TestCase):
    def setUp(self):
        self.menu = Menu.objects.create(pk=2, name='Dinner')
        self.page = MenuPage.objects.create(
            menu=self.menu, name='Mains', heading='Mains', decorative_title='Dinner',
        )
        self.dish = Dish.objects.create(menu_page=self.page, name='Curry', price='125.50')
        self.staff = get_user_model().objects.create_user(username='orders-staff', is_staff=True)
        self.url = reverse('create-order', args=[self.menu.pk])

    def payload(self):
        return {
            'submission_id': str(uuid4()), 'customer_name': 'Test guest',
            'phone': '+47 123 45 678', 'note': 'No cutlery',
            'items': [{'dish_id': self.dish.pk, 'quantity': 2}],
        }

    def test_shop_status_is_public_but_only_staff_and_superusers_can_change_it(self):
        url = reverse('shop-status')
        response = self.client.get(url)
        self.assertTrue(response.json()['is_open'])
        self.assertIn('no-store', response['Cache-Control'])
        data = {'is_open': False, 'expected_is_open': True}
        self.assertEqual(self.client.patch(url, data, content_type='application/json').status_code, 401)
        ordinary = get_user_model().objects.create_user(username='shop-customer')
        self.client.force_login(ordinary)
        self.assertEqual(self.client.patch(url, data, content_type='application/json').status_code, 403)
        superuser = get_user_model().objects.create_user(username='shop-super', is_superuser=True)
        for user in [self.staff, superuser]:
            with self.subTest(user=user):
                ShopStatus.objects.filter(pk=1).update(is_open=True)
                self.client.force_login(user)
                self.assertEqual(self.client.patch(url, data, content_type='application/json').status_code, 200)
                self.assertFalse(Client().get(url).json()['is_open'])
        self.assertContains(Client().get('/'), 'data-shop-open="false"')
        self.assertEqual(ShopStatus.objects.count(), 1)

    def test_shop_changes_require_csrf_boolean_fields_and_the_expected_current_state(self):
        url = reverse('shop-status')
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.staff)
        client.get('/')
        data = {'is_open': False, 'expected_is_open': True}
        self.assertEqual(client.patch(url, data, content_type='application/json').status_code, 403)
        token = client.cookies[settings.CSRF_COOKIE_NAME].value
        self.assertEqual(client.patch(
            url, data, content_type='application/json', HTTP_X_CSRFTOKEN=token,
        ).status_code, 200)
        self.assertEqual(client.patch(
            url, data, content_type='application/json', HTTP_X_CSRFTOKEN=token,
        ).status_code, 409)
        self.client.force_login(self.staff)
        for invalid in [
            {}, {'is_open': 'true', 'expected_is_open': False},
            {'is_open': 1, 'expected_is_open': False},
            {'is_open': True, 'expected_is_open': False, 'extra': True},
        ]:
            with self.subTest(data=invalid):
                self.assertEqual(self.client.patch(url, invalid, content_type='application/json').status_code, 400)
        self.assertFalse(ShopStatus.objects.get(pk=1).is_open)

    @override_settings(WS_INTERNAL_URL='http://127.0.0.1:8002/', WS_INTERNAL_NOTIFY_TOKEN='test-only')
    def test_shop_changes_publish_only_public_hints_after_commit(self):
        self.client.force_login(self.staff)
        url = reverse('shop-status')
        with patch('meny.orders.notify.run') as delivery:
            for is_open in [False, True]:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.patch(
                        url, {'is_open': is_open, 'expected_is_open': not is_open},
                        content_type='application/json',
                    )
                    self.assertEqual(response.status_code, 200)
                    delivery.assert_not_called()
                delivery.assert_called_once_with({}, 'public:shop', 'shop.changed')
                delivery.reset_mock()
            with self.captureOnCommitCallbacks(execute=True):
                self.client.patch(
                    url, {'is_open': True, 'expected_is_open': True}, content_type='application/json',
                )
                self.client.patch(
                    url, {'is_open': True, 'expected_is_open': False}, content_type='application/json',
                )
            delivery.assert_not_called()
        with patch('meny.orders.notify.run', side_effect=RuntimeError('test-only failure')):
            with self.assertLogs('meny.orders', level='WARNING'), self.captureOnCommitCallbacks(execute=True):
                response = self.client.patch(
                    url, {'is_open': False, 'expected_is_open': True}, content_type='application/json',
                )
            self.assertEqual(response.status_code, 200)
            self.assertFalse(ShopStatus.objects.get(pk=1).is_open)

    def test_closed_shop_rejects_new_orders_but_preserves_receipts_and_existing_order_management(self):
        original = self.payload()
        order_id = self.place(original).json()['order']['id']
        ShopStatus.objects.filter(pk=1).update(is_open=False)
        new = self.payload()
        response = self.place(new)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['error'], 'shop_closed')
        self.assertFalse(response.json()['is_open'])
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(self.place(original).json()['order']['id'], order_id)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(self.client.get(reverse('customer-orders')).json()['results'][0]['id'], order_id)
        self.client.force_login(self.staff)
        response = self.client.patch(
            reverse('order-status', args=[order_id]),
            {'status': 'preparing', 'expected_status': 'new'}, content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.patch(
            reverse('shop-status'), {'is_open': True, 'expected_is_open': False},
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.place(new).status_code, 201)
        self.assertEqual(Order.objects.count(), 2)

    def place(self, data=None, client=None):
        return (client or self.client).post(self.url, data or self.payload(), content_type='application/json')

    def test_guest_checkout_stores_authoritative_price_and_durable_snapshots(self):
        data = self.payload()
        response = self.place(data)
        self.assertEqual(response.status_code, 201)
        order = Order.objects.get()
        self.assertEqual(response.json(), {'order': {'id': order.pk, 'total': '251.00', 'currency': 'NOK'}})
        self.assertEqual(order.customer_name, data['customer_name'])
        self.assertEqual(order.phone, data['phone'])
        self.assertEqual(order.note, data['note'])
        self.assertEqual(order.status, Order.Status.NEW)
        self.dish.name = 'Renamed'
        self.dish.price = '999.00'
        self.dish.save()
        self.assertEqual(order.items.get().name, 'Curry')
        self.assertEqual(str(order.items.get().unit_price), '125.50')
        self.menu.delete()
        order.refresh_from_db()
        self.assertIsNone(order.menu_id)
        self.assertEqual(order.menu_name, 'Dinner')
        self.assertIsNone(order.items.get().dish_id)
        self.assertEqual(str(order.total), '251.00')
        self.assertIn('no-store', response['Cache-Control'])

    def test_retry_after_lost_response_reuses_order_even_if_menu_was_deleted(self):
        data = self.payload()
        first = self.place(data)
        self.menu.delete()
        retry = self.place(data)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(first.json(), retry.json())
        self.assertEqual(Order.objects.count(), 1)
        data['note'] = 'Different order'
        self.assertEqual(self.place(data).status_code, 409)
        self.assertEqual(Order.objects.count(), 1)

    def test_invalid_inputs_and_client_price_overrides_do_not_create_orders(self):
        other_menu = Menu.objects.create(name='Other')
        other_page = MenuPage.objects.create(
            menu=other_menu, name='Other', heading='Other', decorative_title='Other',
        )
        other_dish = Dish.objects.create(menu_page=other_page, name='Other', price='1.00')
        cases = [
            {'customer_name': ''}, {'customer_name': 'x' * 151}, {'customer_name': 5},
            {'phone': 'abc'}, {'phone': '123'}, {'phone': '1' * 33}, {'note': 'x' * 2001},
            {'submission_id': 'invalid'}, {'submission_id': 123},
            {'total': '0.01'}, {'status': 'completed'},
            {'items': []}, {'items': {}},
            {'items': [{'dish_id': self.dish.pk, 'quantity': True}]},
            {'items': [{'dish_id': self.dish.pk, 'quantity': 0}]},
            {'items': [{'dish_id': self.dish.pk, 'quantity': 100}]},
            {'items': [{'dish_id': True, 'quantity': 1}]},
            {'items': [{'dish_id': 2**64, 'quantity': 1}]},
            {'items': [{'dish_id': other_dish.pk, 'quantity': 1}]},
            {'items': [{'dish_id': self.dish.pk, 'quantity': 1, 'price': '0.01'}]},
            {'items': [{'dish_id': self.dish.pk, 'quantity': 1}] * 2},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertEqual(self.place({**self.payload(), **changes}).status_code, 400)
        self.assertEqual(self.client.post(self.url, 'bad', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(self.url, 'null', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.post(self.url, {}).status_code, 415)
        self.assertEqual(self.client.post(self.url, 'x' * 17000, content_type='application/json').status_code, 413)
        self.assertEqual(Order.objects.count(), 0)

    def test_unavailable_and_unpriced_dishes_rejected_but_free_dishes_allowed(self):
        for price in (None, '-1.00'):
            self.dish.price = price
            self.dish.save()
            self.assertEqual(self.place().status_code, 400)
        self.dish.price = '0.00'
        self.dish.save()
        self.assertEqual(self.place().json()['order']['total'], '0.00')
        data = self.payload()
        self.dish.delete()
        self.assertEqual(self.place(data).status_code, 400)

    def test_hidden_dishes_and_categories_reject_old_baskets_without_breaking_receipt_retries(self):
        data = self.payload()
        original = self.place(data)
        self.assertEqual(original.status_code, 201)
        self.dish.is_visible = False
        self.dish.save()
        self.assertEqual(self.place().status_code, 400)
        self.assertEqual(self.place(data).json(), original.json())
        self.dish.is_visible = True
        self.dish.save()
        continuation = MenuPage.objects.create(
            menu=self.menu, name='More mains', decorative_title='More', is_continuation=True, position=1,
        )
        extra = Dish.objects.create(menu_page=continuation, name='Extra curry', price='99.00')
        self.page.is_visible = False
        self.page.save()
        self.assertEqual(self.place().status_code, 400)
        extra_data = {**self.payload(), 'items': [{'dish_id': extra.pk, 'quantity': 1}]}
        self.assertEqual(self.place(extra_data).status_code, 400)
        self.assertEqual(self.place(data).json(), original.json())
        self.assertEqual(Order.objects.count(), 1)
        self.page.is_visible = True
        self.page.save()
        self.assertEqual(self.place(extra_data).status_code, 201)

    def test_csrf_required_for_guest_checkout_and_staff_status_changes(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.place(client=client).status_code, 403)
        page = client.get('/')
        self.assertContains(page, 'data-cart-open')
        token = client.cookies[settings.CSRF_COOKIE_NAME].value
        response = client.post(self.url, self.payload(), content_type='application/json', HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 201)
        client.force_login(self.staff)
        url = reverse('order-status', args=[response.json()['order']['id']])
        body = {'status': 'preparing', 'expected_status': 'new'}
        self.assertEqual(client.patch(url, body, content_type='application/json').status_code, 403)
        self.assertEqual(
            client.patch(url, body, content_type='application/json', HTTP_X_CSRFTOKEN=token).status_code, 200,
        )

    def test_order_data_and_management_are_staff_only_including_superusers(self):
        order_id = self.place().json()['order']['id']
        list_url = reverse('order-list')
        status_url = reverse('order-status', args=[order_id])
        ordinary = get_user_model().objects.create_user(username='order-customer')
        superuser = get_user_model().objects.create_user(username='order-super', is_superuser=True)
        self.assertRedirects(self.client.get('/orders'), '/orders/', status_code=301, fetch_redirect_response=False)
        self.assertRedirects(
            self.client.get('/orders/'), '/orders/login/?next=/orders/', fetch_redirect_response=False,
        )
        for user, status in [(None, 401), (ordinary, 403), (self.staff, 200), (superuser, 200)]:
            if user:
                self.client.force_login(user)
            else:
                self.client.logout()
            with self.subTest(user=user):
                response = self.client.get(list_url)
                self.assertEqual(response.status_code, status)
                self.assertIn('no-store', response['Cache-Control'])
                self.assertEqual(self.client.get('/orders/').status_code, 302 if user is None else status)
                self.assertEqual(
                    self.client.patch(status_url, {'status': 'new', 'expected_status': 'new'},
                                      content_type='application/json').status_code, status,
                )
                if status != 200:
                    self.assertNotContains(response, 'Test guest', status_code=status)

    def test_status_workflow_cancellation_and_stale_updates(self):
        order_id = self.place().json()['order']['id']
        url = reverse('order-status', args=[order_id])
        self.client.force_login(self.staff)
        def update(status, expected):
            return self.client.patch(url, {'status': status, 'expected_status': expected},
                                     content_type='application/json')
        self.assertEqual(update('completed', 'new').status_code, 409)
        self.assertEqual(update('preparing', 'new').status_code, 200)
        self.assertEqual(update('ready', 'new').status_code, 409)
        self.assertEqual(update('ready', 'preparing').status_code, 200)
        self.assertEqual(update('completed', 'ready').status_code, 200)
        self.assertEqual(update('cancelled', 'completed').status_code, 409)
        self.assertEqual(update('new', 'completed').status_code, 409)
        self.assertEqual(update('completed', 'ready').status_code, 200)
        self.assertEqual(self.client.get(reverse('order-list')).json()['count'], 0)
        completed = self.client.get(reverse('order-list'), {'status': 'completed'}).json()['results'][0]
        self.assertEqual(completed['next_statuses'], [])
        self.assertEqual(completed['items'][0]['total'], '251.00')
        for status in ('new', 'preparing', 'ready'):
            self.place()
            order = Order.objects.first()
            Order.objects.filter(pk=order.pk).update(status=status)
            response = self.client.patch(reverse('order-status', args=[order.pk]),
                                         {'status': 'cancelled', 'expected_status': status},
                                         content_type='application/json')
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(reverse('order-list'), {'status': 'all'}).json()['count'], 4)
        self.assertEqual(self.client.get(reverse('order-list'), {'status': 'bad'}).status_code, 400)
        self.assertEqual(self.client.get(reverse('order-list'), {'page': 'bad'}).status_code, 400)
        self.assertEqual(update([], 'completed').status_code, 400)

    @override_settings(WS_INTERNAL_URL='http://127.0.0.1:8002/', WS_INTERNAL_NOTIFY_TOKEN='test-only')
    def test_committed_orders_notify_active_staff_and_own_customer_without_contact_details(self):
        superuser = get_user_model().objects.create_user(username='notify-super', is_superuser=True)
        get_user_model().objects.create_user(username='not-staff')
        get_user_model().objects.create_user(username='inactive-staff', is_staff=True, is_active=False)
        with patch('meny.orders.notify.run') as delivery:
            with self.captureOnCommitCallbacks(execute=True):
                order_id = self.place().json()['order']['id']
                delivery.assert_not_called()
            channel = f'orders:{Order.objects.get(pk=order_id).customer_channel}'
            self.assertEqual(
                {call.args[1] for call in delivery.call_args_list},
                {self.staff.pk, superuser.pk, channel},
            )
            for call in delivery.call_args_list:
                self.assertEqual(call.args[0], {'order_id': order_id})
                self.assertEqual(call.args[2], 'orders.changed')
            delivery.reset_mock()
            self.client.force_login(self.staff)
            with self.captureOnCommitCallbacks(execute=True):
                self.client.patch(reverse('order-status', args=[order_id]),
                                  {'status': 'preparing', 'expected_status': 'new'},
                                  content_type='application/json')
            self.assertEqual(delivery.call_count, 3)

    def test_customer_status_is_private_to_browser_session_and_survives_reload(self):
        self.client.get('/')
        channel = self.client.session['order_channel']
        own_id = self.place().json()['order']['id']
        other = Client()
        other.get('/')
        other_id = self.place(client=other).json()['order']['id']
        self.assertNotEqual(channel, other.session['order_channel'])
        url = reverse('customer-orders')
        response = self.client.get(url, {'order_id': other_id, 'customer_channel': other.session['order_channel']})
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        own = response.json()['results']
        self.assertEqual([order['id'] for order in own], [own_id])
        self.assertEqual(set(own[0]), {'id', 'status', 'status_label', 'updated_at'})
        self.assertEqual(own[0]['status'], 'new')
        self.assertNotContains(response, channel)
        self.assertNotContains(response, 'Test guest')
        self.assertNotContains(response, '+47 123 45 678')
        self.assertEqual([order['id'] for order in other.get(url).json()['results']], [other_id])
        self.assertEqual(Client().get(url).json(), {'results': []})
        self.client.get('/')
        self.assertEqual(self.client.session['order_channel'], channel)
        Order.objects.filter(pk=own_id).update(status='ready')
        self.assertEqual(self.client.get(url).json()['results'][0]['status_label'], 'Klar')
        self.client.logout()
        self.assertEqual(self.client.get(url).json(), {'results': []})

    def test_lost_checkout_response_uses_the_session_established_before_checkout(self):
        self.client.get('/')
        channel = self.client.session['order_channel']
        data = self.payload()
        self.place(data)
        self.place(data)
        self.assertEqual(str(Order.objects.get().customer_channel), channel)
        self.assertEqual(len(self.client.get(reverse('customer-orders')).json()['results']), 1)

    def test_customer_status_includes_all_unfinished_orders_and_recent_completion_of_an_old_order(self):
        self.client.get('/')
        channel = self.client.session['order_channel']
        orders = Order.objects.bulk_create([
            Order(
                menu=self.menu, menu_name=self.menu.name, submission_id=uuid4(),
                request_fingerprint='test', customer_channel=channel,
                customer_name='Test guest', phone='12345678', total='1.00',
                status=Order.Status.NEW if index < 30 else Order.Status.COMPLETED,
            )
            for index in range(60)
        ])
        url = reverse('customer-orders')
        results = self.client.get(url).json()['results']
        self.assertTrue({order.pk for order in orders[:30]}.issubset({order['id'] for order in results}))
        self.assertEqual(sum(order['status'] == 'completed' for order in results), 25)
        oldest = orders[0]
        oldest.status = Order.Status.COMPLETED
        oldest.save(update_fields=['status', 'updated_at'])
        results = self.client.get(url).json()['results']
        self.assertIn(
            {'id': oldest.pk, 'status': 'completed', 'status_label': 'Fullført',
             'updated_at': oldest.updated_at.isoformat()},
            results,
        )
        self.assertTrue({order.pk for order in orders[1:30]}.issubset({order['id'] for order in results}))
        self.assertEqual(Client().get(url).json(), {'results': []})

    @override_settings(INTERNAL_AUTH_TOKEN='test-only-auth')
    def test_customer_socket_auth_requires_service_token_and_an_existing_session(self):
        url = reverse('customer-order-auth')
        headers = {'HTTP_AUTHORIZATION': 'Bearer test-only-auth'}
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(Client().get(url, **headers).status_code, 401)
        self.client.get('/')
        channel = self.client.session['order_channel']
        response = self.client.get(url, **headers)
        self.assertEqual(response.json(), {'user_id': f'orders:{channel}'})
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(self.client.post(url, **headers).status_code, 405)
        self.assertEqual(self.client.get(url, HTTP_AUTHORIZATION='Bearer wrong').status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url, **headers).status_code, 401)
        with override_settings(INTERNAL_AUTH_TOKEN=''):
            self.assertEqual(self.client.get(url, **headers).status_code, 503)

    @override_settings(WS_INTERNAL_URL='http://127.0.0.1:8002/', WS_INTERNAL_NOTIFY_TOKEN='test-only')
    def test_notification_failure_does_not_lose_or_duplicate_order(self):
        data = self.payload()
        with patch('meny.orders.notify.run', side_effect=OSError('offline')):
            with self.assertLogs('meny.orders', level='WARNING'), self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self.place(data).status_code, 201)
            self.assertEqual(self.place(data).status_code, 200)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderItem.objects.count(), 1)


class FrontendReloadTests(SimpleTestCase):
    def configure_reload(self):
        return runpy.run_path(str(Path(__file__).resolve().parents[1] / 'manage.py'))['configure_frontend_reload']

    def test_dev_hup_touches_a_file_watched_by_the_django_autoreloader(self):
        with tempfile.TemporaryDirectory() as directory:
            trigger = Path(directory) / 'reload'
            with (
                patch.dict(os.environ, {'DJANGO_RELOAD_TRIGGER': str(trigger)}),
                patch('signal.signal') as install,
                patch('django.utils.autoreload.autoreload_started.connect') as connect,
            ):
                self.configure_reload()()
            self.assertTrue(trigger.exists())
            self.assertEqual(install.call_args.args[0], signal.SIGHUP)
            reloader = Mock(extra_files=set())
            connect.call_args.args[0](sender=reloader)
            self.assertIn(trigger, reloader.extra_files)
            trigger.unlink()
            install.call_args.args[1](signal.SIGHUP, None)
            self.assertTrue(trigger.exists())

    def test_normal_django_commands_do_not_install_a_hup_handler(self):
        with patch.dict(os.environ, {'DJANGO_RELOAD_TRIGGER': ''}), patch('signal.signal') as install:
            self.configure_reload()()
        install.assert_not_called()
