import hashlib
import re
from uuid import UUID

from django.conf import settings
from django.http import JsonResponse

from .models import NativeAppRegistration
from .play_integrity import normalize_certificate_digest


def registration_for_request(request, platform, role=None, appid=None):
    enabled = (
        settings.APP_ATTEST_ENABLED
        if platform == NativeAppRegistration.Platform.IOS
        else settings.PLAY_INTEGRITY_ENABLED
    )
    if not enabled:
        return None, JsonResponse({'error': 'App verification is disabled.'}, status=503)
    try:
        registration_id = UUID(request.headers.get('X-App-Registration-ID', ''))
    except (ValueError, TypeError):
        return None, JsonResponse({'error': 'App registration required.'}, status=401)
    registration = NativeAppRegistration.objects.select_related('restaurant').filter(
        pk=registration_id, platform=platform, enabled=True,
    ).first()
    if registration is None:
        return None, JsonResponse({'error': 'App registration is unavailable.'}, status=503)
    if role is not None and registration.role != role:
        return None, JsonResponse({'error': 'App registration has the wrong role.'}, status=401)
    if registration.role == NativeAppRegistration.Role.CUSTOMER and (
        registration.restaurant_id is None
        or not registration.restaurant.active
        or (appid is not None and str(registration.restaurant.appid) != str(appid))
    ):
        return None, JsonResponse({'error': 'Restaurant not found.'}, status=404)
    if platform == NativeAppRegistration.Platform.ANDROID and (
        not re.fullmatch(r'[A-Za-z]\w*(?:\.[A-Za-z]\w*)+', registration.app_id, flags=re.ASCII)
        or not isinstance(registration.certificate_digests, list)
        or not registration.certificate_digests
        or any(normalize_certificate_digest(value) is None for value in registration.certificate_digests)
    ):
        return None, JsonResponse({'error': 'Play Integrity is not configured.'}, status=503)
    return registration, None


def management_client_data_hash(challenge, body_hash, registration_id, operation):
    scope = f'POST\nmanagement\n{registration_id}\n{operation}\n'.encode()
    return hashlib.sha256(scope + challenge + body_hash).digest()
