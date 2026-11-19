import json
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.contrib.auth import authenticate
from django.db import transaction
from django.db.models import Max
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.middleware.csrf import get_token
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .forms import RestaurantRegistrationForm
from .models import (
    ALLERGEN_CHOICES, Dish, Menu, MenuPage, Order, Restaurant, RestaurantMembership,
    ShopStatus, visible_menu_pages,
)
from .orders import TRANSITIONS, _publish_order, _publish_shop, ensure_order_channel, get_shop_status
from .tokens import InvalidToken, issue_token_pair, revoke_refresh_token, rotate_refresh_token, user_from_access_token


def _read_json(request):
    if request.content_type != 'application/json':
        return None, JsonResponse({'error': _('Expected application/json.')}, status=415)
    if len(request.body) > 16 * 1024:
        return None, JsonResponse({'error': _('Payload too large.')}, status=413)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        data = None
    if not isinstance(data, dict):
        return None, JsonResponse({'error': _('Invalid JSON.')}, status=400)
    return data, None


def _form_errors(form):
    return {
        field: [item['message'] for item in errors]
        for field, errors in form.errors.get_json_data().items()
    }


@never_cache
@ensure_csrf_cookie
@require_GET
def customer_session(request):
    ensure_order_channel(request)
    return JsonResponse({'csrf_token': get_token(request)})


@never_cache
@require_POST
def register_restaurant(request):
    data, error = _read_json(request)
    if error:
        return error
    if set(data) != {'restaurant_name', 'email', 'password', 'password_confirm'}:
        return JsonResponse({'error': _('Invalid fields.')}, status=400)
    form = RestaurantRegistrationForm(data)
    if not form.is_valid():
        return JsonResponse({'errors': _form_errors(form)}, status=400)
    user, restaurant = form.save()
    return JsonResponse({
        'status': 'pending_approval',
        'email': user.email,
        'restaurant': {
            'name': restaurant.name,
            'appid': str(restaurant.appid),
            'active': restaurant.active,
        },
    }, status=201)


@never_cache
@csrf_exempt
@require_POST
def obtain_tokens(request):
    data, error = _read_json(request)
    if error:
        return error
    if set(data) != {'email', 'password'} or not all(
        isinstance(data[field], str) for field in ('email', 'password')
    ):
        return JsonResponse({'error': _('Invalid credentials.')}, status=400)
    email = data['email'].strip().lower()
    user = authenticate(request, username=email, password=data['password'])
    if user is None:
        return JsonResponse({'error': _('Invalid credentials.')}, status=401)
    return JsonResponse({
        **issue_token_pair(user),
        'user': {'id': user.pk, 'email': user.email},
    })


@never_cache
@csrf_exempt
@require_POST
def refresh_tokens(request):
    data, error = _read_json(request)
    if error:
        return error
    if set(data) != {'refresh'} or not isinstance(data.get('refresh'), str):
        return JsonResponse({'error': _('Invalid refresh token.')}, status=400)
    try:
        tokens = rotate_refresh_token(data['refresh'])
    except InvalidToken:
        return JsonResponse({'error': _('Invalid refresh token.')}, status=401)
    return JsonResponse(tokens)


@never_cache
@csrf_exempt
@require_POST
def logout_tokens(request):
    data, error = _read_json(request)
    if error:
        return error
    if set(data) != {'refresh'} or not isinstance(data.get('refresh'), str):
        return JsonResponse({'error': _('Invalid refresh token.')}, status=400)
    try:
        revoke_refresh_token(data['refresh'])
    except InvalidToken:
        return JsonResponse({'error': _('Invalid refresh token.')}, status=401)
    return JsonResponse({'logged_out': True})


def _jwt_user(request):
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    if scheme.lower() != 'bearer' or not token:
        return None
    return user_from_access_token(token)


def _management_access(request, appid):
    user = _jwt_user(request)
    if user is None:
        return None, JsonResponse({'error': _('Authentication required.')}, status=401)
    restaurant = get_object_or_404(Restaurant, appid=appid)
    if user.is_staff or user.is_superuser or RestaurantMembership.objects.filter(
        user=user, restaurant=restaurant,
    ).exists():
        return (user, restaurant), None
    return None, JsonResponse({'error': _('You do not have access to this restaurant.')}, status=403)


def _menu_document(menu):
    pages = list(menu.pages.prefetch_related('dishes').all())
    visible_ids = {page.pk for page in visible_menu_pages(pages)}
    categories = []
    current_category = None
    for page in pages:
        if page.pk not in visible_ids or page.layout == MenuPage.Layout.COVER:
            continue
        if not page.is_continuation:
            current_category = {'id': page.pk, 'name': page.name, 'dishes': []}
            categories.append(current_category)
        if current_category is not None:
            current_category['dishes'].extend([
                {
                    'id': dish.pk,
                    'name': dish.name,
                    'description': dish.description,
                    'price': format(dish.price, '.2f') if dish.price is not None else None,
                    'allergens': dish.allergens,
                }
                for dish in page.dishes.all() if dish.is_visible
            ])
    return {
        'id': menu.pk,
        'name': menu.name,
        'categories': categories,
    }


@never_cache
@require_GET
def public_restaurant_status(request, appid):
    restaurant = get_object_or_404(Restaurant, appid=appid, active=True)
    return JsonResponse({
        'restaurant': restaurant.name,
        **get_shop_status(restaurant),
    })


@never_cache
@require_GET
def public_menus(request, appid):
    restaurant = get_object_or_404(Restaurant, appid=appid, active=True)
    menus = restaurant.menus.all()
    return JsonResponse({
        'restaurant': {'name': restaurant.name, 'appid': str(restaurant.appid)},
        'default_menu_id': next((menu.pk for menu in menus if menu.is_default), None),
        'results': [
            {'id': menu.pk, 'name': menu.name, 'is_default': menu.is_default}
            for menu in menus
        ],
    })


@never_cache
@require_GET
def public_default_menu(request, appid):
    restaurant = get_object_or_404(Restaurant, appid=appid, active=True)
    menu = get_object_or_404(restaurant.menus, is_default=True)
    return JsonResponse(_menu_document(menu))


@never_cache
@require_GET
def public_menu(request, appid, menu_id):
    restaurant = get_object_or_404(Restaurant, appid=appid, active=True)
    menu = get_object_or_404(restaurant.menus, pk=menu_id)
    return JsonResponse(_menu_document(menu))


@never_cache
@require_GET
def management_restaurants(request):
    user = _jwt_user(request)
    if user is None:
        return JsonResponse({'error': _('Authentication required.')}, status=401)
    if user.is_staff or user.is_superuser:
        restaurants = Restaurant.objects.all()
        role = 'admin'
        return JsonResponse({'results': [
            {
                'name': restaurant.name,
                'appid': str(restaurant.appid),
                'active': restaurant.active,
                'role': role,
            }
            for restaurant in restaurants
        ]})
    memberships = RestaurantMembership.objects.filter(
        user=user,
    ).select_related('restaurant').order_by('restaurant__name')
    return JsonResponse({'results': [
        {
            'name': membership.restaurant.name,
            'appid': str(membership.restaurant.appid),
            'active': membership.restaurant.active,
            'role': membership.role,
        }
        for membership in memberships
    ]})


@never_cache
@require_GET
def management_menus(request, appid):
    access, error = _management_access(request, appid)
    if error:
        return error
    _user, restaurant = access
    menus = restaurant.menus.all()
    return JsonResponse({'results': [
        {'id': menu.pk, 'name': menu.name, 'is_default': menu.is_default}
        for menu in menus
    ]})


def _management_category_groups(menu, lock=False):
    pages = menu.pages
    if lock:
        pages = pages.select_for_update()
    groups = []
    current = None
    for page in pages.order_by('position', 'pk').prefetch_related('dishes'):
        if page.layout == MenuPage.Layout.COVER:
            current = None
        elif not page.is_continuation:
            current = [page]
            groups.append(current)
        elif current is not None:
            current.append(page)
    return groups


def _management_menu_content(menu):
    categories = []
    for group in _management_category_groups(menu):
        page = group[0]
        dishes = []
        for member in group:
            dishes.extend({
                'id': dish.pk,
                'page_id': member.pk,
                'name': dish.name,
                'description': dish.description,
                'price': format(dish.price, '.2f') if dish.price is not None else None,
                'allergens': dish.allergens,
                'is_visible': dish.is_visible,
            } for dish in member.dishes.all())
        categories.append({
            'id': page.pk,
            'name': page.name,
            'is_visible': page.is_visible,
            'dishes': dishes,
        })
    return {
        'id': menu.pk,
        'name': menu.name,
        'categories': categories,
    }


def _management_category(menu, category_id, lock=False):
    return next(
        (group for group in _management_category_groups(menu, lock=lock)
         if group[0].pk == category_id),
        None,
    )


@never_cache
@require_GET
def management_menu_content(request, appid, menu_id):
    access, error = _management_access(request, appid)
    if error:
        return error
    _user, restaurant = access
    menu = get_object_or_404(restaurant.menus, pk=menu_id)
    return JsonResponse(_management_menu_content(menu))


@never_cache
@csrf_exempt
@require_POST
def create_management_menu(request, appid):
    access, error = _management_access(request, appid)
    if error:
        return error
    _user, restaurant = access
    data, error = _read_json(request)
    if error:
        return error
    if set(data) - {'name'} or not isinstance(data.get('name'), str) or not data['name'].strip():
        return JsonResponse({'error': _('Invalid fields.')}, status=400)
    name = data['name'].strip()
    if len(name) > 150:
        return JsonResponse({'error': _('Menu name is too long.')}, status=400)
    with transaction.atomic():
        menu = Menu.objects.create(restaurant=restaurant, name=name)
    return JsonResponse({
        'id': menu.pk,
        'name': menu.name,
        'is_default': menu.is_default,
    }, status=201)


@never_cache
@csrf_exempt
@require_POST
def create_management_category(request, appid, menu_id):
    access, error = _management_access(request, appid)
    if error:
        return error
    _user, restaurant = access
    data, error = _read_json(request)
    if error:
        return error
    if set(data) != {'name'} or not isinstance(data.get('name'), str):
        return JsonResponse({'error': _('Invalid fields.')}, status=400)
    name = data['name'].strip()
    if not name or len(name) > 150:
        return JsonResponse({'error': _('Invalid fields.')}, status=400)

    with transaction.atomic():
        menu = get_object_or_404(Menu.objects.select_for_update(), restaurant=restaurant, pk=menu_id)
        pages = list(menu.pages.select_for_update().order_by('position', 'pk'))
        insert_at = len(pages) - 1 if pages and pages[-1].layout == MenuPage.Layout.COVER else len(pages)
        page = MenuPage(
            menu=menu,
            name=name,
            heading=name,
            decorative_title=name,
            position=insert_at,
        )
        try:
            page.full_clean()
        except ValidationError:
            return JsonResponse({'error': _('Invalid fields.')}, status=400)
        page.save()
        pages.insert(insert_at, page)
        for position, item in enumerate(pages):
            item.position = position
        MenuPage.objects.bulk_update(pages, ['position'])
    return JsonResponse({
        'id': page.pk,
        'name': page.name,
        'is_visible': page.is_visible,
        'dishes': [],
    }, status=201)


@never_cache
@csrf_exempt
@require_http_methods(['PATCH', 'DELETE'])
def management_category(request, appid, menu_id, category_id):
    access, error = _management_access(request, appid)
    if error:
        return error
    _user, restaurant = access

    with transaction.atomic():
        menu = get_object_or_404(Menu.objects.select_for_update(), restaurant=restaurant, pk=menu_id)
        pages = list(menu.pages.select_for_update().order_by('position', 'pk'))
        group = next(
            (candidate for candidate in _management_category_groups(menu, lock=True)
             if candidate[0].pk == category_id),
            None,
        )
        if group is None:
            return JsonResponse({'error': _('Category not found.')}, status=404)
        category = group[0]

        if request.method == 'DELETE':
            deleted_ids = {page.pk for page in group}
            menu.pages.filter(pk__in=deleted_ids).delete()
            pages = [page for page in pages if page.pk not in deleted_ids]
            for position, page in enumerate(pages):
                page.position = position
            MenuPage.objects.bulk_update(pages, ['position'])
            return JsonResponse({'deleted': True})

        data, error = _read_json(request)
        if error:
            return error
        if set(data) != {'name'} or not isinstance(data.get('name'), str):
            return JsonResponse({'error': _('Invalid fields.')}, status=400)
        name = data['name'].strip()
        if not name or len(name) > 150:
            return JsonResponse({'error': _('Invalid fields.')}, status=400)
        category.name = name
        category.heading = name
        category.decorative_title = name
        try:
            category.full_clean()
        except ValidationError:
            return JsonResponse({'error': _('Invalid fields.')}, status=400)
        category.save(update_fields=['name', 'heading', 'decorative_title'])
    return JsonResponse({'id': category.pk, 'name': category.name, 'is_visible': category.is_visible})


def _management_update_dish(dish, data, creating=False):
    fields = {'name', 'description', 'price', 'allergens', 'is_visible'}
    if not isinstance(data, dict) or set(data) - fields or (creating and 'name' not in data):
        return JsonResponse({'error': _('Invalid fields.')}, status=400)
    errors = {}
    if 'is_visible' in data:
        if type(data['is_visible']) is not bool:
            errors['is_visible'] = [_('Invalid fields.')]
        else:
            dish.is_visible = data['is_visible']
    for field in ('name', 'description'):
        if field in data:
            if not isinstance(data[field], str):
                errors[field] = [_('Invalid fields.')]
            else:
                setattr(dish, field, data[field].strip())
    if 'price' in data:
        value = data['price']
        if value is None or value == '':
            dish.price = None
        else:
            try:
                if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                    raise InvalidOperation
                price = Decimal(str(value).replace(',', '.'))
                if not price.is_finite() or price < 0:
                    raise InvalidOperation
                dish.price = price
            except InvalidOperation:
                errors['price'] = [_('Invalid fields.')]
    if 'allergens' in data:
        valid_allergens = dict(ALLERGEN_CHOICES)
        if not isinstance(data['allergens'], list) or not all(
            isinstance(value, str) and value in valid_allergens for value in data['allergens']
        ):
            errors['allergens'] = [_('Invalid fields.')]
        else:
            dish.allergens = list(dict.fromkeys(data['allergens']))
    try:
        dish.full_clean()
    except ValidationError as error:
        errors.update({
            field: [str(message) for message in messages]
            for field, messages in error.message_dict.items()
        })
    if errors:
        return JsonResponse({'error': _('Invalid fields.'), 'errors': errors}, status=400)
    dish.save()
    return JsonResponse({
        'id': dish.pk,
        'page_id': dish.menu_page_id,
        'name': dish.name,
        'description': dish.description,
        'price': format(dish.price, '.2f') if dish.price is not None else None,
        'allergens': dish.allergens,
        'is_visible': dish.is_visible,
    }, status=201 if creating else 200)


@never_cache
@csrf_exempt
@require_POST
def create_management_dish(request, appid, menu_id, category_id):
    access, error = _management_access(request, appid)
    if error:
        return error
    _user, restaurant = access
    data, error = _read_json(request)
    if error:
        return error
    with transaction.atomic():
        menu = get_object_or_404(Menu.objects.select_for_update(), restaurant=restaurant, pk=menu_id)
        group = _management_category(menu, category_id, lock=True)
        if group is None:
            return JsonResponse({'error': _('Category not found.')}, status=404)
        page = group[-1]
        last_position = page.dishes.aggregate(last=Max('position'))['last']
        dish = Dish(
            menu_page=page,
            position=last_position + 1 if last_position is not None else 0,
        )
        return _management_update_dish(dish, data, creating=True)


@never_cache
@csrf_exempt
@require_http_methods(['PATCH', 'DELETE'])
def management_dish(request, appid, menu_id, dish_id):
    access, error = _management_access(request, appid)
    if error:
        return error
    _user, restaurant = access
    with transaction.atomic():
        menu = get_object_or_404(Menu.objects.select_for_update(), restaurant=restaurant, pk=menu_id)
        dish = get_object_or_404(
            Dish.objects.select_for_update().select_related('menu_page'),
            pk=dish_id,
            menu_page__menu=menu,
        )
        if request.method == 'DELETE':
            dish.delete()
            return JsonResponse({'deleted': True})
        data, error = _read_json(request)
        if error:
            return error
        return _management_update_dish(dish, data)


@never_cache
@csrf_exempt
@require_POST
def set_management_default_menu(request, appid, menu_id):
    access, error = _management_access(request, appid)
    if error:
        return error
    _user, restaurant = access
    menu = get_object_or_404(Menu, restaurant=restaurant, pk=menu_id)
    menu.is_default = True
    menu.save(update_fields=['is_default'])
    return JsonResponse({'id': menu.pk, 'is_default': menu.is_default})


@never_cache
@csrf_exempt
@require_http_methods(['GET', 'PATCH'])
def management_shop_status(request, appid):
    access, error = _management_access(request, appid)
    if error:
        return error
    _user, restaurant = access
    if request.method == 'GET':
        return JsonResponse(get_shop_status(restaurant))

    data, error = _read_json(request)
    if error:
        return error
    if set(data) != {'is_open', 'expected_is_open'} or any(
        type(value) is not bool for value in data.values()
    ):
        return JsonResponse({'error': _('Invalid fields.')}, status=400)
    with transaction.atomic():
        shop, _created = ShopStatus.objects.select_for_update().get_or_create(restaurant=restaurant)
        if shop.is_open != data['expected_is_open']:
            return JsonResponse({'error': _('Shop status changed.')}, status=409)
        changed = shop.is_open != data['is_open']
        shop.is_open = data['is_open']
        shop.save(update_fields=['is_open'])
        if changed:
            transaction.on_commit(lambda: _publish_shop(restaurant.appid), robust=True)
    return JsonResponse(get_shop_status(restaurant))


@never_cache
@require_GET
def management_orders(request, appid):
    access, error = _management_access(request, appid)
    if error:
        return error
    _user, restaurant = access
    orders = Order.objects.filter(restaurant=restaurant).prefetch_related('items')
    status = request.GET.get('status', 'active')
    if status == 'active':
        orders = orders.exclude(status__in=[Order.Status.COMPLETED, Order.Status.CANCELLED])
    elif status != 'all':
        if status not in Order.Status.values:
            return JsonResponse({'error': _('Invalid status.')}, status=400)
        orders = orders.filter(status=status)
    paginator = Paginator(orders, 25)
    try:
        page = paginator.page(request.GET.get('page', 1))
    except (PageNotAnInteger, EmptyPage):
        return JsonResponse({'error': _('Invalid page.')}, status=400)
    return JsonResponse({
        'results': [
            {
                'id': order.pk,
                'customer_name': order.customer_name,
                'phone': order.phone,
                'note': order.note,
                'menu_name': order.menu_name,
                'status': order.status,
                'status_label': order.get_status_display(),
                'next_statuses': list(TRANSITIONS[order.status]),
                'total': str(order.total),
                'currency': 'NOK',
                'created_at': order.created_at.isoformat(),
                'updated_at': order.updated_at.isoformat(),
                'status_url': reverse(
                    'management-order-status',
                    kwargs={'appid': restaurant.appid, 'order_id': order.pk},
                ),
                'items': [
                    {
                        'name': item.name,
                        'quantity': item.quantity,
                        'unit_price': str(item.unit_price),
                        'total': str(item.unit_price * item.quantity),
                    }
                    for item in order.items.all()
                ],
            }
            for order in page
        ],
        'count': paginator.count,
        'page': page.number,
        'pages': paginator.num_pages,
    })


@never_cache
@csrf_exempt
@require_http_methods(['PATCH'])
def management_order_status(request, appid, order_id):
    access, error = _management_access(request, appid)
    if error:
        return error
    _user, restaurant = access
    data, error = _read_json(request)
    if error:
        return error
    if set(data) != {'status', 'expected_status'} or any(
        not isinstance(data[key], str) or data[key] not in Order.Status.values
        for key in ('status', 'expected_status')
    ):
        return JsonResponse({'error': _('Invalid status.')}, status=400)
    with transaction.atomic():
        order = get_object_or_404(
            Order.objects.select_for_update(), restaurant=restaurant, pk=order_id,
        )
        if data['status'] == order.status:
            return JsonResponse({'status': order.status})
        if data['expected_status'] != order.status or data['status'] not in TRANSITIONS[order.status]:
            return JsonResponse({'error': _('The order changed. Refresh and try again.')}, status=409)
        changed = Order.objects.filter(
            pk=order.pk, restaurant=restaurant, status=data['expected_status'],
        ).update(status=data['status'], updated_at=timezone.now())
        if not changed:
            return JsonResponse({'error': _('The order changed. Refresh and try again.')}, status=409)
        transaction.on_commit(lambda: _publish_order(order.pk), robust=True)
    return JsonResponse({'status': data['status']})
