import base64
import hashlib
import json
import re
import secrets
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .orders import create_order, ensure_order_channel
from .models import PlayIntegrityChallenge
from .native_apps import registration_for_request
from .play_integrity import (
    InvalidPlayIntegrity,
    PlayIntegrityUnavailable,
    decode_integrity_token,
    play_integrity_request_hash,
    verify_integrity_payload,
)


REQUEST_HASH_PATTERN = re.compile(r'^[0-9a-f]{64}$')
CHALLENGE_LIFETIME = timedelta(minutes=5)


def _read_json(request):
    if request.content_type != 'application/json' or len(request.body) > 256 * 1024:
        return None
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _customer_channel(request):
    try:
        return UUID(request.session.get('order_channel'))
    except (TypeError, ValueError):
        return None


@never_cache
@require_POST
def play_integrity_challenge(request):
    registration, error = registration_for_request(request, 'android')
    if error is not None:
        return error
    data = _read_json(request)
    request_hash = data.get('request_hash') if data is not None else None
    if (
        data is None
        or set(data) != {'request_hash'}
        or not isinstance(request_hash, str)
        or not REQUEST_HASH_PATTERN.fullmatch(request_hash)
    ):
        return JsonResponse({'error': 'Invalid Play Integrity challenge request.'}, status=400)

    channel_id = _customer_channel(request)
    if channel_id is None:
        ensure_order_channel(request)
        channel_id = _customer_channel(request)

    now = timezone.now()
    PlayIntegrityChallenge.objects.filter(expires_at__lte=now).delete()
    active_challenges = PlayIntegrityChallenge.objects.filter(
        customer_channel=channel_id,
        app_registration=registration,
        consumed_at__isnull=True,
        expires_at__gt=now,
    ).count()
    if active_challenges >= 10:
        return JsonResponse({'error': 'Too many active Play Integrity challenges.'}, status=429)
    challenge = PlayIntegrityChallenge.objects.create(
        customer_channel=channel_id,
        app_registration=registration,
        challenge=secrets.token_bytes(32),
        request_hash=request_hash,
        expires_at=now + CHALLENGE_LIFETIME,
    )
    return JsonResponse({
        'challenge_id': str(challenge.pk),
        'challenge': base64.b64encode(bytes(challenge.challenge)).decode(),
    })


@never_cache
@require_POST
def create_play_integrity_order(request, appid, menu_id):
    registration, error = registration_for_request(request, 'android', 'customer', appid)
    if error is not None:
        return error
    return with_play_integrity_proof(
        request,
        registration,
        lambda challenge, request_hash: play_integrity_request_hash(
            challenge, bytes.fromhex(request_hash), registration.app_id, appid, menu_id,
        ),
        lambda: create_order(
            request, menu_id, appid, verified_app_registration=registration,
        ),
    )


def with_play_integrity_proof(request, registration, hash_for_challenge, action):
    if len(request.body) > 16 * 1024:
        return JsonResponse({'error': 'Payload too large.'}, status=413)

    token = request.headers.get('X-Play-Integrity-Token', '')
    try:
        challenge_id = UUID(request.headers.get('X-Play-Integrity-Challenge-ID', ''))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Play Integrity proof required.'}, status=401)
    channel_id = _customer_channel(request)
    if channel_id is None or not token:
        return JsonResponse({'error': 'Play Integrity proof required.'}, status=401)

    request_hash = hashlib.sha256(request.body).hexdigest()
    challenge_query = PlayIntegrityChallenge.objects.filter(
        pk=challenge_id,
        customer_channel=channel_id,
        app_registration=registration,
        request_hash=request_hash,
        consumed_at__isnull=True,
        expires_at__gt=timezone.now(),
    )
    challenge = challenge_query.first()
    if challenge is None:
        return JsonResponse({'error': 'Invalid or expired Play Integrity challenge.'}, status=401)
    expected_hash = hash_for_challenge(bytes(challenge.challenge), request_hash)

    try:
        payload = decode_integrity_token(token, registration.app_id)
        verify_integrity_payload(
            payload,
            expected_hash,
            registration.app_id,
            registration.certificate_digests,
        )
    except InvalidPlayIntegrity:
        return JsonResponse({'error': 'Play Integrity verification failed.'}, status=401)
    except PlayIntegrityUnavailable:
        return JsonResponse({'error': 'Play Integrity verification is unavailable.'}, status=503)

    try:
        with transaction.atomic():
            challenge = PlayIntegrityChallenge.objects.select_for_update().get(
                pk=challenge_id,
                customer_channel=channel_id,
                app_registration=registration,
                request_hash=request_hash,
                consumed_at__isnull=True,
                expires_at__gt=timezone.now(),
            )
            challenge.consumed_at = timezone.now()
            challenge.save(update_fields=['consumed_at'])
            response = action()
    except PlayIntegrityChallenge.DoesNotExist:
        return JsonResponse({'error': 'Invalid or expired Play Integrity challenge.'}, status=401)
    return response
