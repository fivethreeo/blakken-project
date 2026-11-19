from django.http import JsonResponse

from .models import RestaurantMembership


def has_restaurant_access(user, restaurant):
    if not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return True
    return RestaurantMembership.objects.filter(user=user, restaurant=restaurant).exists()


def restaurant_access_error(request, restaurant):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Unauthenticated'}, status=401)
    if not has_restaurant_access(request.user, restaurant):
        return JsonResponse({'error': 'Forbidden'}, status=403)
    return None
