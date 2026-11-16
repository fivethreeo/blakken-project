from decimal import Decimal, InvalidOperation
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import transaction
from django.db.models import Max
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.crypto import constant_time_compare
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .celery import app
from .models import ALLERGEN_CHOICES, Dish, Job, Menu, MenuPage


@never_cache
@require_GET
def index(request):
    menu = get_object_or_404(Menu.objects.prefetch_related('pages__dishes'), pk=2)
    return render(request, 'index.html', {'menu': menu})


@never_cache
@require_GET
def menu_pages(request, menu_id):
    menu = get_object_or_404(Menu.objects.prefetch_related('pages__dishes'), pk=menu_id)
    return render(request, 'menu/pages.html', {'menu': menu})


def _dish_response(dish, status=200):
    response = JsonResponse({
        'dish': {
            'id': dish.pk,
            'name': dish.name,
            'description': dish.description,
            'price': format(dish.price, '.2f') if dish.price is not None else None,
            'allergens': dish.allergens,
        },
        'allergen_choices': ALLERGEN_CHOICES,
        'create_url': reverse('dish-list', args=[dish.menu_page.menu_id, dish.menu_page_id]),
        'category_slug': dish.menu_page.slug,
    }, status=status)
    if status == 201:
        response['Location'] = reverse('dish-detail', args=[dish.menu_page.menu_id, dish.pk])
    return response


def _save_dish(request, dish):
    if request.content_type != 'application/json':
        return JsonResponse({'error': 'Expected application/json'}, status=415)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    fields = {'name', 'description', 'price', 'allergens'}
    if not isinstance(data, dict) or set(data) - fields:
        return JsonResponse({'error': 'Invalid fields'}, status=400)
    errors = {}
    for field in ('name', 'description'):
        if field not in data:
            continue
        if not isinstance(data[field], str):
            errors[field] = ['Skriv inn tekst.']
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
                price = Decimal(str(value))
                if not price.is_finite() or price < 0:
                    raise InvalidOperation
                dish.price = price
            except InvalidOperation:
                errors['price'] = ['Skriv inn en gyldig pris på null eller mer.']
    if 'allergens' in data:
        selected = data['allergens']
        allowed = dict(ALLERGEN_CHOICES)
        if not isinstance(selected, list) or not all(
            isinstance(value, str) and value in allowed for value in selected
        ):
            errors['allergens'] = ['Velg gyldige allergener.']
        else:
            dish.allergens = list(dict.fromkeys(selected))
    try:
        dish.full_clean()
    except ValidationError as error:
        errors.update(error.message_dict)
    if errors:
        return JsonResponse({'errors': errors}, status=400)
    creating = dish.pk is None
    if creating:
        dish.save()
    else:
        dish.save(update_fields=list(data))
    return _dish_response(dish, status=201 if creating else 200)


@never_cache
@require_http_methods(['GET', 'PATCH', 'DELETE'])
def dish_detail(request, menu_id, dish_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'error': 'Forbidden'}, status=403)
    dish = get_object_or_404(
        Dish.objects.select_related('menu_page'), pk=dish_id, menu_page__menu_id=menu_id,
    )
    if request.method == 'DELETE':
        dish.delete()
        return HttpResponse(status=204)
    if request.method == 'PATCH':
        return _save_dish(request, dish)
    return _dish_response(dish)


@never_cache
@require_POST
def dish_list(request, menu_id, page_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'error': 'Forbidden'}, status=403)
    with transaction.atomic():
        page = get_object_or_404(MenuPage.objects.select_for_update(), pk=page_id, menu_id=menu_id)
        last = page.dishes.aggregate(last=Max('position'))['last']
        dish = Dish(menu_page=page, position=last + 1 if last is not None else 0)
        return _save_dish(request, dish)


@never_cache
@require_POST
def move_dish(request, menu_id, dish_id):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'error': 'Forbidden'}, status=403)
    direction = request.POST.get('direction')
    if direction not in ('up', 'down'):
        return JsonResponse({'error': 'Invalid direction'}, status=400)

    with transaction.atomic():
        page = get_object_or_404(
            MenuPage.objects.select_for_update(),
            menu_id=menu_id,
            pk__in=Dish.objects.filter(pk=dish_id).values('menu_page_id'),
        )
        dishes = list(page.dishes.select_for_update())
        index = next((index for index, dish in enumerate(dishes) if dish.pk == dish_id), None)
        if index is None:
            raise Http404
        neighbor = index + (-1 if direction == 'up' else 1)
        if neighbor < 0 or neighbor >= len(dishes):
            return JsonResponse({'moved': False})
        dishes[index], dishes[neighbor] = dishes[neighbor], dishes[index]
        for position, dish in enumerate(dishes):
            dish.position = position
        Dish.objects.bulk_update(dishes, ['position'])
    return JsonResponse({'moved': True})


@never_cache
@require_GET
def auth(request):
    token = settings.INTERNAL_AUTH_TOKEN
    if not token:
        return JsonResponse({'error': 'Unavailable'}, status=503)

    if not constant_time_compare(
        request.headers.get('Authorization', ''),
        f'Bearer {token}',
    ):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)

    return JsonResponse({'user_id': request.user.pk})


@never_cache
@require_GET
def job_results(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)

    paginator = Paginator(Job.objects.filter(user=request.user), 25)
    try:
        page = paginator.page(request.GET.get('page', 1))
    except PageNotAnInteger:
        return JsonResponse({'error': 'Invalid page'}, status=400)
    except EmptyPage:
        return JsonResponse({'error': 'Page not found'}, status=404)

    jobs = list(page.object_list)
    if jobs and not app.conf.result_backend:
        return JsonResponse({'error': 'Celery result storage is not configured'}, status=503)

    results = []
    for job in jobs:
        try:
            metadata = app.backend.get_task_meta(job.task_id, cache=False)
        except Exception:
            return JsonResponse({'error': 'Unable to retrieve task results'}, status=503)
        status = metadata.get('status', 'PENDING')
        results.append({
            'id': job.pk,
            'task_id': job.task_id,
            'created_at': job.created_at,
            'status': status,
            'result': metadata.get('result') if status == 'SUCCESS' else None,
        })

    try:
        return JsonResponse({
            'count': paginator.count,
            'page': page.number,
            'pages': paginator.num_pages,
            'results': results,
        })
    except (TypeError, ValueError, OverflowError):
        return JsonResponse({'error': 'Unable to encode task results'}, status=503)
