import hashlib
import json
import logging
import re
from decimal import Decimal
from uuid import UUID, uuid4

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .models import Dish, Menu, Order, OrderItem, ShopStatus, visible_menu_pages
from .tasks import notify


logger = logging.getLogger(__name__)
TRANSITIONS = {
    Order.Status.NEW: (Order.Status.PREPARING, Order.Status.CANCELLED),
    Order.Status.PREPARING: (Order.Status.READY, Order.Status.CANCELLED),
    Order.Status.READY: (Order.Status.COMPLETED, Order.Status.CANCELLED),
    Order.Status.COMPLETED: (),
    Order.Status.CANCELLED: (),
}


def _is_staff(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


def _shop_data(shop):
    return {
        'is_open': shop.is_open,
        'message': (
            'Vi har åpent for bestillinger. Bestill via handlekurven nederst til høyre.'
            if shop.is_open else
            'Vi har stengt for bestillinger. Du kan fortsatt lese menyen, men ikke sende bestillinger nå.'
        ),
    }


def get_shop_status():
    shop, _ = ShopStatus.objects.get_or_create(pk=1)
    return _shop_data(shop)


@never_cache
@require_http_methods(['GET', 'PATCH'])
def shop_status(request):
    if request.method == 'GET':
        return JsonResponse(get_shop_status())
    error = _staff_error(request)
    if error is not None:
        return error
    data, error = _read_json(request)
    if error is not None:
        return error
    if set(data) != {'is_open', 'expected_is_open'} or any(type(value) is not bool for value in data.values()):
        return JsonResponse({'error': 'Invalid fields'}, status=400)
    with transaction.atomic():
        shop, _ = ShopStatus.objects.select_for_update().get_or_create(pk=1)
        if shop.is_open != data['expected_is_open']:
            return JsonResponse({'error': 'Shop status changed', **_shop_data(shop)}, status=409)
        changed = shop.is_open != data['is_open']
        shop.is_open = data['is_open']
        shop.save(update_fields=['is_open'])
        if changed:
            transaction.on_commit(_publish_shop, robust=True)
    return JsonResponse(_shop_data(shop))


def _publish_shop():
    if not settings.WS_INTERNAL_URL or not settings.WS_INTERNAL_NOTIFY_TOKEN:
        return
    try:
        notify.run({}, 'public:shop', 'shop.changed')
    except Exception:
        logger.warning('Shop status saved but a WebSocket notification failed.')


class OrderAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not _is_staff(user):
            raise ValidationError('Kun ansatte har tilgang til bestillinger.', code='invalid_login')


def _staff_error(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)
    if not _is_staff(request.user):
        return JsonResponse({'error': 'Forbidden'}, status=403)
    return None


def _publish_order(order_id):
    if not settings.WS_INTERNAL_URL or not settings.WS_INTERNAL_NOTIFY_TOKEN:
        return
    staff = get_user_model().objects.filter(is_active=True).filter(Q(is_staff=True) | Q(is_superuser=True))
    recipients = list(staff.values_list('pk', flat=True))
    channel = Order.objects.filter(pk=order_id).values_list('customer_channel', flat=True).first()
    if channel:
        recipients.append(f'orders:{channel}')
    for user_id in recipients:
        try:
            # Only a hint travels over the socket; HTTP rechecks access to order data.
            notify.run({'order_id': order_id}, user_id, 'orders.changed')
        except Exception:
            logger.warning('Order saved but a WebSocket notification failed.')


def ensure_order_channel(request):
    channel = request.session.get('order_channel')
    if not channel:
        channel = str(uuid4())
        request.session['order_channel'] = channel
    return channel


@never_cache
@require_GET
def customer_orders(request):
    channel = request.session.get('order_channel')
    orders = []
    if channel:
        own_orders = Order.objects.filter(customer_channel=channel)
        active = (Order.Status.NEW, Order.Status.PREPARING, Order.Status.READY)
        recent_finished = own_orders.exclude(status__in=active).order_by('-updated_at', '-pk').values('pk')[:25]
        orders = own_orders.filter(Q(status__in=active) | Q(pk__in=recent_finished))
    return JsonResponse({'results': [
        {'id': order.pk, 'status': order.status, 'status_label': order.get_status_display(),
         'updated_at': order.updated_at.isoformat()}
        for order in orders
    ]})


@never_cache
@require_GET
def customer_order_auth(request):
    if not settings.INTERNAL_AUTH_TOKEN:
        return JsonResponse({'error': 'Unavailable'}, status=503)
    if not constant_time_compare(
        request.headers.get('Authorization', ''), f'Bearer {settings.INTERNAL_AUTH_TOKEN}',
    ):
        return JsonResponse({'error': 'Forbidden'}, status=403)
    channel = request.session.get('order_channel')
    if not channel:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)
    return JsonResponse({'user_id': f'orders:{channel}'})


def _read_json(request):
    if request.content_type != 'application/json':
        return None, JsonResponse({'error': 'Expected application/json'}, status=415)
    if len(request.body) > 16 * 1024:
        return None, JsonResponse({'error': 'Payload too large'}, status=413)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        data = None
    if not isinstance(data, dict):
        return None, JsonResponse({'error': 'Invalid JSON'}, status=400)
    return data, None


def _receipt(order, status=200):
    return JsonResponse({'order': {'id': order.pk, 'total': str(order.total), 'currency': 'NOK'}}, status=status)


@never_cache
@require_POST
def create_order(request, menu_id):
    data, error = _read_json(request)
    if error is not None:
        return error
    if set(data) != {'submission_id', 'customer_name', 'phone', 'note', 'items'}:
        return JsonResponse({'error': 'Invalid fields'}, status=400)
    try:
        if not isinstance(data['submission_id'], str):
            raise ValueError
        submission_id = UUID(data['submission_id'])
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({'error': 'Invalid submission ID'}, status=400)
    errors = {}
    for field, limit in [('customer_name', 150), ('phone', 32), ('note', 2000)]:
        value = data[field]
        if not isinstance(value, str) or len(value.strip()) > limit or (field != 'note' and not value.strip()):
            errors[field] = 'Kontroller dette feltet.'
        else:
            data[field] = value.strip()
    if 'phone' not in errors and (
        not re.fullmatch(r'\+?[0-9 ()-]+', data['phone'])
        or not 7 <= len(re.sub(r'\D', '', data['phone'])) <= 15
    ):
        errors['phone'] = 'Skriv inn et gyldig telefonnummer.'
    items = data['items']
    if not isinstance(items, list) or not 1 <= len(items) <= 50:
        errors['items'] = 'Velg mellom 1 og 50 forskjellige retter.'
    else:
        ids = set()
        for item in items:
            if (
                not isinstance(item, dict) or set(item) != {'dish_id', 'quantity'}
                or type(item['dish_id']) is not int or not 0 < item['dish_id'] < 2**63
                or item['dish_id'] in ids
                or type(item['quantity']) is not int or not 1 <= item['quantity'] <= 99
            ):
                errors['items'] = 'Kontroller rettene og antall (1–99).'
                break
            ids.add(item['dish_id'])
    if errors:
        return JsonResponse({'errors': errors}, status=400)
    normalized = {**data, 'submission_id': str(submission_id), 'menu_id': menu_id,
                  'items': sorted(items, key=lambda item: item['dish_id'])}
    fingerprint = hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest()

    with transaction.atomic():
        shop, _ = ShopStatus.objects.select_for_update().get_or_create(pk=1)
        existing = Order.objects.filter(submission_id=submission_id).first()
        if existing:
            if existing.request_fingerprint != fingerprint:
                return JsonResponse({'error': 'Submission ID already used for another order'}, status=409)
            return _receipt(existing)
        if not shop.is_open:
            return JsonResponse({'error': 'shop_closed', **_shop_data(shop)}, status=409)
        menu = get_object_or_404(Menu, pk=menu_id)
        visible_pages = [page.pk for page in visible_menu_pages(menu.pages.all())]
        dishes = {dish.pk: dish for dish in Dish.objects.filter(
            menu_page_id__in=visible_pages, is_visible=True, pk__in=ids,
        )}
        if len(dishes) != len(ids) or any(
            dish.price is None or dish.price < 0 for dish in dishes.values()
        ):
            return JsonResponse({'errors': {'items': 'En rett er ikke tilgjengelig. Last menyen på nytt.'}}, status=400)
        total = sum((dishes[item['dish_id']].price * item['quantity'] for item in items), Decimal('0.00'))
        order, created = Order.objects.get_or_create(
            submission_id=submission_id,
            defaults={
                'menu': menu, 'menu_name': menu.name, 'request_fingerprint': fingerprint,
                'customer_name': data['customer_name'], 'phone': data['phone'],
                'note': data['note'], 'total': total,
                'customer_channel': ensure_order_channel(request),
            },
        )
        if not created:
            if order.request_fingerprint != fingerprint:
                return JsonResponse({'error': 'Submission ID already used for another order'}, status=409)
            return _receipt(order)
        OrderItem.objects.bulk_create([
            OrderItem(order=order, dish=dishes[item['dish_id']], name=dishes[item['dish_id']].name,
                      quantity=item['quantity'], unit_price=dishes[item['dish_id']].price)
            for item in items
        ])
        transaction.on_commit(lambda: _publish_order(order.pk), robust=True)
    return _receipt(order, status=201)


@never_cache
@require_GET
@login_required(login_url='orders-login')
def orders_page(request):
    if not _is_staff(request.user):
        return HttpResponseForbidden('Kun ansatte har tilgang til bestillinger.')
    return render(request, 'orders.html', {'statuses': Order.Status.choices, 'shop': get_shop_status()})


def _serialize(order):
    return {
        'id': order.pk, 'customer_name': order.customer_name, 'phone': order.phone,
        'note': order.note, 'menu_name': order.menu_name,
        'status': order.status, 'status_label': order.get_status_display(),
        'next_statuses': list(TRANSITIONS[order.status]),
        'total': str(order.total), 'currency': 'NOK',
        'created_at': order.created_at.isoformat(), 'updated_at': order.updated_at.isoformat(),
        'status_url': reverse('order-status', args=[order.pk]),
        'items': [{'name': item.name, 'quantity': item.quantity, 'unit_price': str(item.unit_price),
                   'total': str(item.unit_price * item.quantity)} for item in order.items.all()],
    }


@never_cache
@require_GET
def order_list(request):
    error = _staff_error(request)
    if error is not None:
        return error
    orders = Order.objects.prefetch_related('items')
    status = request.GET.get('status', 'active')
    if status == 'active':
        orders = orders.exclude(status__in=[Order.Status.COMPLETED, Order.Status.CANCELLED])
    elif status != 'all':
        if status not in Order.Status.values:
            return JsonResponse({'error': 'Invalid status'}, status=400)
        orders = orders.filter(status=status)
    paginator = Paginator(orders, 25)
    try:
        page = paginator.page(request.GET.get('page', 1))
    except (PageNotAnInteger, EmptyPage):
        return JsonResponse({'error': 'Invalid page'}, status=400)
    return JsonResponse({'results': [_serialize(order) for order in page],
                         'count': paginator.count, 'page': page.number, 'pages': paginator.num_pages})


@never_cache
@require_http_methods(['PATCH'])
def order_status(request, order_id):
    error = _staff_error(request)
    if error is not None:
        return error
    data, error = _read_json(request)
    if error is not None:
        return error
    if set(data) != {'status', 'expected_status'} or any(
        not isinstance(data[key], str) or data[key] not in Order.Status.values
        for key in ('status', 'expected_status')
    ):
        return JsonResponse({'error': 'Invalid status'}, status=400)
    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update(), pk=order_id)
        if data['status'] == order.status:
            return JsonResponse({'status': order.status})
        if data['expected_status'] != order.status or data['status'] not in TRANSITIONS[order.status]:
            return JsonResponse({'error': 'Bestillingen er endret. Oppdater listen og prøv igjen.'}, status=409)
        changed = Order.objects.filter(pk=order.pk, status=data['expected_status']).update(
            status=data['status'], updated_at=timezone.now(),
        )
        if not changed:
            return JsonResponse({'error': 'Bestillingen er endret. Oppdater listen og prøv igjen.'}, status=409)
        transaction.on_commit(lambda: _publish_order(order.pk), robust=True)
    return JsonResponse({'status': data['status']})
